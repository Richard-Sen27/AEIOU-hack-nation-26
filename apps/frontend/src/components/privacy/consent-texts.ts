import type { ConsentType } from "@/lib/api/types";

/**
 * The just-in-time notices shown in the consent dialog (GDPR Art. 9(2)(a)
 * explicit consent, Art. 13 notice; CCPA notice at collection). The version
 * is stored with every grant (`POST /consents`), so bump it whenever the
 * wording below changes in substance.
 */
export const CONSENT_VERSION: Record<ConsentType, string> = {
  upload: "upload-2026-10-04",
  contribute: "contribute-2026-10-04",
};

export type ConsentNotice = {
  /** One-sentence summary of what the user agrees to. */
  summary: string;
  /** "What we process" (categories of personal and sensitive information). */
  processed: string[];
  /** "Why" (purpose). */
  purpose: string;
  /** How the data is protected and handled. */
  safeguards: string[];
  /** Retention, per category. */
  retention: string[];
  /** How to withdraw, and what withdrawal deletes. */
  withdrawal: string;
  /** The explicit statement next to the (unticked) checkbox. */
  agreement: string;
  /** Button that grants the consent. */
  grantLabel: string;
};

export const CONSENT_NOTICES: Record<ConsentType, ConsentNotice> = {
  upload: {
    summary:
      "To read a report for you, Amber has to process the health and genetic information in it. We need your explicit consent for that.",
    processed: [
      "The document you upload (a genetic report, clinical letter, research paper or registry document).",
      "Health and genetic information found in it: diagnoses, genes, variants, symptoms, test dates. These are sensitive personal information.",
      "The findings you confirm, which are added to your private profile.",
    ],
    purpose:
      "Only to extract findings for you to review and, once you confirm them, to find connections in the atlas for you. Never for advertising, profiling or training AI models.",
    safeguards: [
      "Names, birth dates, addresses and patient IDs are removed on our server before any AI model sees the text.",
      "The original file is deleted right after the text is extracted. We never keep it.",
      "Only the redacted text goes to OpenAI, running on your own ChatGPT plan.",
      "Nothing is sold or shared. Nothing goes into the shared atlas unless you separately agree to contribute.",
    ],
    retention: [
      "Original file: deleted immediately after extraction.",
      "Findings, and profile items that came from documents: kept until you delete them, withdraw this consent or delete your account.",
    ],
    withdrawal:
      "You can withdraw at any time in your profile with one click. Withdrawing deletes your uploaded documents, their findings and processing jobs, and the items in your profile that came from documents.",
    agreement:
      "I explicitly consent to Amber processing the health and genetic information in documents I upload, as described above.",
    grantLabel: "I agree, continue",
  },
  contribute: {
    summary:
      "Contributing adds information you choose to the shared atlas that everyone can see. We need your separate, explicit consent for that.",
    processed: [
      "Only what you submit in the contribution form: a disease, symptoms present or absent and an optional age range, or a resource such as a registry or natural history study.",
      "Health information in a symptom profile is sensitive personal information.",
      "It is stored with a link to your account so you can see and remove it, but it is shown in the atlas without your name or email.",
    ],
    purpose:
      "To help other families and researchers see patterns and find existing work. Contributions are labelled patient-reported, wait for review, and are never treated as cited evidence.",
    safeguards: [
      "Never include names, birth dates, addresses, patient IDs or anything else that identifies a person.",
      "Nothing is sold or shared for advertising. No medical information is disclosed to patient groups or researchers beyond the contribution you choose to publish.",
      "Your private profile stays private. Contributing does not publish it.",
    ],
    retention: [
      "Contributions: kept until you remove them, withdraw this consent or delete your account.",
    ],
    withdrawal:
      "You can withdraw at any time in your profile with one click. Withdrawing removes all your contributions from the shared atlas.",
    agreement:
      "I explicitly consent to Amber publishing the contributions I submit in the shared atlas, labelled as patient-reported, as described above.",
    grantLabel: "I agree, continue",
  },
};

/** What withdrawing deletes, for the profile's consent section. */
export const WITHDRAWAL_EFFECT: Record<ConsentType, string> = {
  upload:
    "Withdrawing deletes your uploaded documents, their findings and processing jobs, and the items in your profile that came from documents.",
  contribute: "Withdrawing removes all your contributions from the shared atlas.",
};

export const CONSENT_LABELS: Record<ConsentType, { title: string; description: string }> = {
  upload: {
    title: "Document upload",
    description: "Lets Amber read reports you upload and extract findings for you to review.",
  },
  contribute: {
    title: "Contribute to the shared atlas",
    description: "Lets you publish patient-reported symptom profiles and resources in the atlas.",
  },
};
