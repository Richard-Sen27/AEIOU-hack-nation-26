import type { Metadata } from "next";

import { PersonCardPage } from "@/components/people/person-card-page";
import { PageContainer } from "@/components/shell/page-placeholder";

// The name is shown to signed-in users only, so it never goes into the page title.
export const metadata: Metadata = { title: "Expert card" };

/** `/people/<card_id>`: a verified doctor's or researcher's opt-in public card. */
export default async function Page(props: PageProps<"/people/[card_id]">) {
  const { card_id } = await props.params;
  return (
    <PageContainer className="max-w-2xl">
      <PersonCardPage key={card_id} cardId={card_id} />
    </PageContainer>
  );
}
