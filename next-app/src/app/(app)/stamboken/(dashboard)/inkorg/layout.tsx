import { QueueUndoProvider } from "./QueueUndo";

export default function InboxLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <QueueUndoProvider>{children}</QueueUndoProvider>;
}
