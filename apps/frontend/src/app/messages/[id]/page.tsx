import { ThreadView } from "@/components/messages/thread-view";

/** `/messages/<opaque thread id>`: the id carries no content. */
export default async function ThreadPage(props: PageProps<"/messages/[id]">) {
  const { id } = await props.params;
  return <ThreadView key={id} id={id} />;
}
