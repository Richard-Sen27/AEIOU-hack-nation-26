"use client";

import { useRouter } from "next/navigation";

import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";
import { useSearch } from "@/components/search/search-provider";
import { PlaceholdersAndVanishInput } from "@/components/ui/placeholders-and-vanish-input";
import { isEntityQuery } from "@/lib/search";

const PLACEHOLDERS = [
  "Tell us about the diagnosis, a gene, or the symptoms, in your own words",
  "STXBP1 encephalopathy",
  "Dravet syndrome",
  "SCN2A",
  "Infantile spasms",
];

/**
 * Landing input (skeleton; the landing feature replaces it). Short names open
 * the global search; free text goes to Dr. Wu, which needs sign-in. The text
 * is never put in a URL.
 */
export function HeroInput() {
  const router = useRouter();
  const { openSearch } = useSearch();
  const { user } = useSession();
  const { requireSignIn } = useGate();

  return (
    <PlaceholdersAndVanishInput
      ariaLabel="Describe the diagnosis, a gene or the symptoms, or search by name"
      placeholders={PLACEHOLDERS}
      maxLength={2000}
      onSubmit={async (value) => {
        if (isEntityQuery(value)) {
          openSearch(value);
          return;
        }
        if (!user) {
          await requireSignIn("Questions in your own words are answered by the AI assistant.", "/chat");
          return;
        }
        router.push("/chat");
      }}
    />
  );
}
