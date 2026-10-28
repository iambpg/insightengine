#!/usr/bin/perl
# Fast liveness probe so Netdisco does not SNMP-walk dead addresses.
#
# Netdisco's own range tool is `netdisco-do pingsweep` (ICMP via the ping
# binary, then a discover job for each reply). `discover -d <cidr>` does not
# do that: it tries SNMP on every address, and with snmp_try_slow_connect the
# second pass costs about a minute per dead address.
#
# This probe treats a host as live when, within one short timeout:
#   * TCP connect succeeds or the host returns ECONNREFUSED (it is up), or
#   * UDP/161 returns a packet or ICMP port-unreachable, or
#   * `ping -c 1` succeeds (needs CAP_NET_RAW or a setuid ping).
# Prefixes larger than /16 are refused (exit 3). Dead or filtered hosts time out
# and are omitted, so the scheduler never calls discover on them.
#
#   perl presweep.pl 10.0.0.0/24
#   perl presweep.pl --self-test
# Prints live addresses, one per line. Does not print the SNMP community.
use strict;
use warnings;
use IO::Select;
use IO::Socket::INET;
use Socket;
use Errno qw(ECONNREFUSED EISCONN);

my $TIMEOUT = $ENV{PRESWEEP_TIMEOUT};
$TIMEOUT = 0.4 unless defined $TIMEOUT && $TIMEOUT =~ /^\d+(?:\.\d+)?$/;
$TIMEOUT = 0.05 if $TIMEOUT < 0.05;
$TIMEOUT = 5 if $TIMEOUT > 5;
my $PARALLEL = $ENV{PRESWEEP_PARALLEL};
$PARALLEL = 64 unless defined $PARALLEL && $PARALLEL =~ /^\d+$/;
$PARALLEL = 1 if $PARALLEL < 1;
$PARALLEL = 256 if $PARALLEL > 256;
my $COMMUNITY = $ENV{SNMP_V2_COMMUNITY} // '';
$COMMUNITY = '' if $COMMUNITY eq 'unset-placeholder';

if (@ARGV && $ARGV[0] eq '--self-test') {
    exit(self_test());
}
die "usage: presweep.pl <ipv4-cidr>\n" unless @ARGV == 1;
my ($ips, $rc) = expand($ARGV[0]);
exit $rc if $rc;
exit 0 unless @$ips;

my @batch;
for my $ip (@$ips) {
    push @batch, $ip;
    if (@batch >= $PARALLEL) {
        drain(@batch);
        @batch = ();
    }
}
drain(@batch) if @batch;
exit 0;

sub expand {
    my ($cidr) = @_;
    return ([], 2) unless defined $cidr && $cidr =~ /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/;
    my @o = ($1, $2, $3, $4);
    my $bits = $5;
    return ([], 2) if grep { $_ > 255 } @o;
    return ([], 3) if $bits < 16 || $bits > 32;
    my $ip = ($o[0] << 24) | ($o[1] << 16) | ($o[2] << 8) | $o[3];
    my $mask = $bits == 0 ? 0 : (0xffffffff << (32 - $bits)) & 0xffffffff;
    my $base = $ip & $mask;
    my $count = 1 << (32 - $bits);
    my $start = $bits <= 30 ? 1 : 0;
    my $end = $bits <= 30 ? $count - 2 : $count - 1;
    my @out;
    for my $i ($start .. $end) {
        my $a = ($base + $i) & 0xffffffff;
        push @out, sprintf('%d.%d.%d.%d', ($a >> 24) & 255, ($a >> 16) & 255, ($a >> 8) & 255, $a & 255);
    }
    return (\@out, 0);
}

sub drain {
    my @ips = @_;
    return unless @ips;
    my %pid;
    for my $ip (@ips) {
        my $child = fork();
        if (!defined $child) {
            print "$ip\n" if probe_host($ip);
            next;
        }
        if ($child == 0) {
            exit(probe_host($ip) ? 0 : 1);
        }
        $pid{$child} = $ip;
    }
    while (%pid) {
        my $p = wait();
        last if !defined $p || $p < 0;
        next unless exists $pid{$p};
        print "$pid{$p}\n" if ($? >> 8) == 0 && ($? & 127) == 0;
        delete $pid{$p};
    }
    return;
}

sub probe_host {
    my ($ip) = @_;
    my $packed_ip = inet_aton($ip);
    return 0 unless $packed_ip;
    my $readers = IO::Select->new();
    my $writers = IO::Select->new();
    my @socks;
    for my $port (22, 23, 80, 443, 830) {
        my $sock = IO::Socket::INET->new(Proto => 'tcp', Type => SOCK_STREAM);
        next unless $sock;
        $sock->blocking(0);
        my $addr = sockaddr_in($port, $packed_ip);
        if (connect($sock, $addr) || $!{EISCONN}) {
            close_all(@socks, $sock);
            return 1;
        }
        if ($!{ECONNREFUSED}) {
            close_all(@socks, $sock);
            return 1;
        }
        $writers->add($sock);
        push @socks, $sock;
    }
    my $udp;
    if ($COMMUNITY ne '') {
        $udp = IO::Socket::INET->new(Proto => 'udp', PeerAddr => $ip, PeerPort => 161);
        if ($udp) {
            $udp->blocking(0);
            $udp->send(snmp_get($COMMUNITY));
            $readers->add($udp);
            push @socks, $udp;
        }
    }
    my $deadline = time() + $TIMEOUT;
    while ($readers->count() > 0 || $writers->count() > 0) {
        my $left = $deadline - time();
        last if $left <= 0;
        my ($ready_r, $ready_w) = IO::Select->select($readers, $writers, undef, $left);
        last unless ($ready_r && @$ready_r) || ($ready_w && @$ready_w);
        for my $sock (@{ $ready_w || [] }) {
            $writers->remove($sock);
            my $packed = getsockopt($sock, SOL_SOCKET, SO_ERROR);
            my $err = $packed ? unpack('i', $packed) : 0;
            if (!$err || $err == ECONNREFUSED) {
                close_all(@socks);
                return 1;
            }
        }
        for my $sock (@{ $ready_r || [] }) {
            $readers->remove($sock);
            my $buf = '';
            my $n = $sock->recv($buf, 512, 0);
            if ((defined $n && length $buf) || $!{ECONNREFUSED}) {
                close_all(@socks);
                return 1;
            }
        }
    }
    close_all(@socks);
    return ping_ok($ip);
}

sub ping_ok {
    my ($ip) = @_;
    return 0 unless $ip =~ /^\d{1,3}(?:\.\d{1,3}){3}$/;
    my $wait = $TIMEOUT < 1 ? 1 : int($TIMEOUT + 0.5);
    my $pid = fork();
    return 0 unless defined $pid;
    if ($pid == 0) {
        open STDOUT, '>', '/dev/null';
        open STDERR, '>', '/dev/null';
        exec 'ping', '-c', '1', '-W', $wait, '-n', $ip;
        exit 1;
    }
    local $SIG{ALRM} = sub { kill 9, $pid; };
    alarm($wait + 1);
    waitpid($pid, 0);
    alarm(0);
    return ($? >> 8) == 0 && ($? & 127) == 0;
}

sub close_all {
    for my $sock (@_) {
        $sock->close() if $sock;
    }
    return;
}

sub snmp_get {
    my ($community) = @_;
    my $oid = pack('C*', 0x2b, 0x06, 0x01, 0x02, 0x01, 0x01, 0x01, 0x00);
    my $varbind = seq(ber_oid($oid) . ber_null());
    my $pdu = ber(0xa0, ber_int(1) . ber_int(0) . ber_int(0) . seq($varbind));
    return seq(ber_int(1) . ber_octets($community) . $pdu);
}

sub ber_int {
    my ($n) = @_;
    my $bytes = pack('C', $n & 0xff);
    return ber(0x02, $bytes);
}

sub ber_octets {
    my ($s) = @_;
    return ber(0x04, $s);
}

sub ber_null { return ber(0x05, ''); }

sub ber_oid { return ber(0x06, $_[0]); }

sub seq { return ber(0x30, $_[0]); }

sub ber {
    my ($tag, $body) = @_;
    return pack('C', $tag) . ber_len(length $body) . $body;
}

sub ber_len {
    my ($n) = @_;
    return pack('C', $n) if $n < 128;
    my $bytes = pack('N', $n);
    $bytes =~ s/^\x00+//;
    return pack('C', 0x80 | length $bytes) . $bytes;
}

sub self_test {
    my ($a, $rc) = expand('10.0.0.0/30');
    die "expand /30\n" unless $rc == 0 && "@$a" eq '10.0.0.1 10.0.0.2';
    my ($big, $big_rc) = expand('10.0.0.0/8');
    die "expand /8 should be refused\n" unless $big_rc == 3 && !@$big;
    my ($bad, $bad_rc) = expand('not-a-cidr');
    die "bad cidr\n" unless $bad_rc == 2;
    my $pkt = snmp_get('public');
    die "snmp packet\n" unless ord(substr($pkt, 0, 1)) == 0x30 && index($pkt, 'public') >= 0;
    my $srv = IO::Socket::INET->new(
        LocalAddr => '127.0.0.1', LocalPort => 0, Proto => 'tcp', Listen => 1, Reuse => 1,
    ) or die "listen: $!\n";
    my $port = $srv->sockport();
    my $child = fork();
    die "fork\n" unless defined $child;
    if ($child == 0) {
        my $client = $srv->accept();
        sleep 1 if $client;
        exit 0;
    }
    my $ok = tcp_open('127.0.0.1', $port, 0.5);
    kill 9, $child;
    waitpid($child, 0);
    $srv->close();
    die "localhost listener was not detected\n" unless $ok;
    my $started = time();
    my $closed = IO::Socket::INET->new(PeerAddr => '127.0.0.1', PeerPort => 1, Proto => 'tcp', Timeout => 0.3);
    $closed->close() if $closed;
    die "closed-port probe hung\n" if time() - $started > 2;
    print "presweep self-test ok\n";
    return 0;
}

sub tcp_open {
    my ($ip, $port, $timeout) = @_;
    my $sock = IO::Socket::INET->new(
        PeerAddr => $ip, PeerPort => $port, Proto => 'tcp', Timeout => $timeout,
    );
    if ($sock) { $sock->close(); return 1; }
    return $!{ECONNREFUSED} ? 1 : 0;
}
