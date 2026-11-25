import Link from "next/link";
import type { Person, QueueUser } from "./lib";

/** An account named in the inbox; an admin gets a link to its page in Admin (#192). */
export function AccountRef({
  person,
  user,
}: {
  person: Person;
  user: QueueUser;
}) {
  return user.is_admin ? (
    <Link href={`/stamboken/admin/anvandare/${person.id}`} className="sb-link">
      {person.name}
    </Link>
  ) : (
    person.name
  );
}
