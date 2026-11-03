import { redirect } from 'next/navigation';

/** The approval queue lives on NetBridge. This route stays so old links still land. */
export default function NotInNetBoxPage() {
  redirect('/netbridge?tab=missing');
}
