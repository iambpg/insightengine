import { redirect } from 'next/navigation';

/** Device parents now live on NetBridge. This route stays so old links still land. */
export default function DeviceParentsPage() {
  redirect('/netbridge?tab=parents');
}
