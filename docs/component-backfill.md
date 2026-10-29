# NetBox component backfill

NetBox copies component templates onto a device only when the device is created. A template added later, or a component deleted by hand, is not filled in. `netbox-component-backfill` walks every device and creates the components its device type defines but the device does not already have.

The match key is the component name. An existing component is not deleted, renamed, or edited. A custom component whose name is not in the templates is left in place. A device whose type has no templates (a discovery stub type is the usual case) is skipped.

The kinds are interfaces, console ports, console server ports, power ports, power outlets, rear ports, front ports, module bays, and device bays. A front port is mapped to the rear port on that same device with the template's rear port name. A power outlet's power port and an interface's bridge are resolved the same way. One bad device does not stop the walk.

## When it runs

Compose service `netbox-component-backfill` builds `insightengine/netbox-component-backfill:local` and runs once after `netbox-device-types` has exited and NetBox is healthy. It reads `secrets/prometheus/netbox.token` and sends `Authorization: Bearer` for a NetBox 4.6 v2 token. It is idempotent: a second run creates nothing.

Nothing else `depends_on` this service. Its NetBox dependency is `required: false`, and the image entrypoint exits 0 even when the backfill does not, so a failure does not stop the rest of the stack. The same rules apply to `netbox-device-types` and `netbox-regions`.

`NETBOX_BACKFILL_COMPONENTS` in `.env` turns the one-shot off. The default is `true`. `false`, `0`, `no`, or `off` makes the container exit without calling NetBox.

`./scripts/upgrade.sh` recreates this service after the device-type importer has exited, the same way it recreates that importer.

## On demand

```bash
docker compose build netbox-component-backfill
./scripts/backfill-netbox-components.sh
./scripts/backfill-netbox-components.sh --dry-run
```

`--dry-run` only prints the summary. It does not create components.

The summary is one line of JSON: `devices_scanned`, `devices_skipped`, `devices_changed`, `created` (a count per kind), `failures`, and `dry_run`.
