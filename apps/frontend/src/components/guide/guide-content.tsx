/**
 * Content of the getting-started guide (`/guide`): one block per feature.
 * Each block: a one-line "what it is", two or three steps, who it is for and
 * a "Try it" target. Describe only what is built (docs/homework.md lists what
 * is not), and never suggest that Amber diagnoses or recommends treatment.
 */
import {
  Activity,
  BadgeCheck,
  Ban,
  Bell,
  Bot,
  Boxes,
  Briefcase,
  ClipboardCheck,
  ClipboardList,
  Download,
  FilePen,
  FileText,
  FileUp,
  Inbox,
  KeyRound,
  ListChecks,
  type LucideIcon,
  Map as MapIcon,
  MapPinOff,
  MessageSquare,
  Network,
  Route,
  Scale,
  Search,
  ShieldAlert,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";

export type Audience = "everyone" | "signed-in" | "patients" | "experts";

export const AUDIENCE_LABEL: Record<Audience, string> = {
  everyone: "Everyone",
  "signed-in": "Sign in",
  patients: "Patients and families",
  experts: "Doctors and researchers",
};

/** Small live illustrations built from the app's own components (see guide-snippets). */
export type SnippetKey = "categories" | "links" | "hypothesis" | "offmap" | "symptoms" | "share";

export type Feature = {
  id: string;
  icon: LucideIcon;
  title: string;
  what: string;
  steps: string[];
  audience: Audience;
  /** A route of the app; `search` opens the global search instead. */
  href: string | "search";
  snippet?: SnippetKey;
};

export type GuideSection = {
  id: string;
  title: string;
  sub: string;
  features: Feature[];
};

/** A disease with rich data in every view (cited genes, groups, trials). Public graph id. */
export const EXAMPLE_NODE = "/node/MONDO:0100135";

export const GUIDE: GuideSection[] = [
  {
    id: "explore",
    title: "Explore the atlas",
    sub: "Free, no account needed.",
    features: [
      {
        id: "search",
        icon: Search,
        title: "Search",
        what: "One box for diseases, genes, symptoms, trials, groups and people.",
        steps: [
          "Press ⌘K (Ctrl K), or the search icon at the top.",
          "Type a name, synonym, acronym (FOP) or id (ORPHA:337, OMIM 135100).",
          "Pick a result to open it.",
        ],
        audience: "everyone",
        href: "search",
      },
      {
        id: "atlas",
        icon: MapIcon,
        title: "Atlas map",
        what: "The whole graph on one map: nine trees, one per kind of thing.",
        steps: [
          "Scroll or pinch to zoom. Click a dot to draw its links and open its card.",
          "The card sums it up; “Write a summary” asks Dr. Wu for a short text (sign in).",
          "Map or List switches to an outline. Tour walks you through in five steps.",
        ],
        audience: "everyone",
        href: "/atlas",
        snippet: "categories",
      },
      {
        id: "node",
        icon: FileText,
        title: "Node pages",
        what: "One item and everything directly linked to it.",
        steps: [
          "Open one from a search result, a card or a link.",
          "Switch Graph or List, and narrow it with “Filter connections”.",
          "Pick a link, then Sources for records and quotes. Export as CSV or GraphML.",
        ],
        audience: "everyone",
        href: EXAMPLE_NODE,
      },
      {
        id: "path",
        icon: Route,
        title: "Find a path",
        what: "The best-supported route between two things, or an honest “no supported route”.",
        steps: [
          "On a node page, press “Find a path to…”.",
          "Choose the end point.",
          "Each step shows its confidence and sources.",
        ],
        audience: "everyone",
        href: "/path",
      },
      {
        id: "clusters",
        icon: Boxes,
        title: "Mechanism groups",
        what: "Diseases the analysis grouped because they share genes, pathways or symptoms.",
        steps: [
          "Browse or search the groups on Clusters.",
          "Open one for its members; Map shows it on the Atlas.",
          "Hypothesis means the atlas grouped them, not a source.",
        ],
        audience: "everyone",
        href: "/clusters",
        snippet: "hypothesis",
      },
      {
        id: "links",
        icon: Network,
        title: "Cited facts, computed links",
        what: "Every link says where it comes from and how sure it is.",
        steps: [
          "Solid: stated by a database or a quoted paper.",
          "Dashed: computed by the atlas, with a one-line reason. Never High.",
          "Click a confidence badge for its breakdown.",
        ],
        audience: "everyone",
        href: "/about-data#trust",
        snippet: "links",
      },
      {
        id: "offmap",
        icon: MapPinOff,
        title: "Not on the map yet",
        what: "The map draws the 169 best-covered diseases; search finds all 7,432.",
        steps: [
          "Search results off the map carry this mark.",
          "Their card and node page work as usual.",
        ],
        audience: "everyone",
        href: "/about-data#scope",
        snippet: "offmap",
      },
    ],
  },
  {
    id: "dr-wu",
    title: "Ask Dr. Wu",
    sub: "An AI assistant that answers from the atlas and cites what it used.",
    features: [
      {
        id: "ask",
        icon: Bot,
        title: "Ask a question",
        what: "Ask in your own words; the answer cites the links it used.",
        steps: [
          "Open Ask Dr. Wu and sign in.",
          "Agree once to the health-data consent.",
          "Ask, then open “Sources” under the answer.",
        ],
        audience: "signed-in",
        href: "/chat",
      },
      {
        id: "symptoms",
        icon: Activity,
        title: "Describe symptoms",
        what: "Conditions ranked by how many of your symptoms they list in the data.",
        steps: [
          "Describe what you notice.",
          "Get a ranking with the overlap and sources for each.",
        ],
        audience: "signed-in",
        href: "/chat",
        snippet: "symptoms",
      },
      {
        id: "wu-map",
        icon: Sparkles,
        title: "Dr. Wu on the map",
        what: "Ask from the Atlas and see the answer drawn on the map.",
        steps: [
          "Open the Dr. Wu dock, bottom left on the Atlas.",
          "“Find …” rings the matching dots; “How is X connected to Y?” draws the route.",
          "On Ask Dr. Wu, “Show in graph” sends an answer to the map.",
        ],
        audience: "signed-in",
        href: "/atlas",
      },
      {
        id: "limits",
        icon: ShieldAlert,
        title: "What Dr. Wu will not do",
        what: "No diagnosis, no treatment advice. Emergencies get an emergency reply.",
        steps: [
          "Answers are information with sources, to discuss with your doctor.",
          "Reloading does not lose an answer in progress; it picks up again.",
        ],
        audience: "signed-in",
        href: "/chat",
      },
    ],
  },
  {
    id: "account",
    title: "Your account",
    sub: "Private to you. Nothing is shared unless you choose to.",
    features: [
      {
        id: "sign-in",
        icon: KeyRound,
        title: "Sign in and set up",
        what: "Two quick choices, then consent only when a feature needs it.",
        steps: [
          "Press Sign in at the top.",
          "Choose patient or family, doctor or researcher, and confirm you are 16 or older.",
          "A feature that handles health data asks for consent the first time.",
        ],
        audience: "everyone",
        href: "/welcome",
      },
      {
        id: "profile",
        icon: UserRound,
        title: "Health profile",
        what: "Your confirmed diagnoses, genes and symptoms.",
        steps: [
          "Add items on Profile, or from a report.",
          "Dr. Wu uses it as context; study suggestions use it if you switch them on.",
          "Edit or remove anything.",
        ],
        audience: "signed-in",
        href: "/profile#health-profile",
      },
      {
        id: "upload",
        icon: FileUp,
        title: "Upload a report",
        what: "Amber reads a report and proposes findings for your profile.",
        steps: [
          "Drop a PDF, photo, Word or text file on Documents (up to 20 MB).",
          "Confirm or drop each finding. Only what you confirm is kept.",
          "The file itself is deleted after reading.",
        ],
        audience: "signed-in",
        href: "/documents",
      },
      {
        id: "follow",
        icon: Bell,
        title: "Follow a disease",
        what: "Updates about it show under the bell.",
        steps: [
          "Press Follow on a disease's card or page.",
          "Check the bell in the top bar.",
          "Manage them on Profile, Following.",
        ],
        audience: "signed-in",
        href: "/profile#following",
      },
      {
        id: "your-data",
        icon: Download,
        title: "Your data and consents",
        what: "Download, delete or withdraw at any time.",
        steps: [
          "Profile, Your data: download everything (JSON) or delete the account.",
          "Profile, Consents: withdraw one; what was held under it is deleted.",
        ],
        audience: "signed-in",
        href: "/profile#your-data",
      },
    ],
  },
  {
    id: "studies",
    title: "Studies",
    sub: "Surveys, studies and trials from verified doctors and researchers.",
    features: [
      {
        id: "browse",
        icon: ClipboardList,
        title: "Browse studies",
        what: "Calls for participants, each with its ethics approval and registry entry.",
        steps: [
          "Open Studies and filter by disease.",
          "Open a call: what it involves, who can take part, dates.",
          "Ask your doctor whether a trial or study could apply to you.",
        ],
        audience: "signed-in",
        href: "/calls",
      },
      {
        id: "sign-up",
        icon: ListChecks,
        title: "Sign up, choose what to share",
        what: "You decide exactly what the study team receives.",
        steps: [
          "Press Sign up on a call.",
          "Tick only what you want to send, pick a display name, add a note if you like.",
        ],
        audience: "patients",
        href: "/calls",
        snippet: "share",
      },
      {
        id: "my-signups",
        icon: ClipboardCheck,
        title: "My sign-ups",
        what: "What you sent, to whom.",
        steps: [
          "Studies, My sign-ups (or Profile, Sign-ups).",
          "Withdraw: what you sent is deleted at once.",
        ],
        audience: "patients",
        href: "/calls/signups",
      },
      {
        id: "suggestions",
        icon: Sparkles,
        title: "Suggestions",
        what: "Off by default. Compares your profile with open calls, inside your account.",
        steps: [
          "Switch on suggestions at the top of Studies.",
          "Agree to the contact consent if asked.",
          "Study teams never learn who was suggested.",
        ],
        audience: "patients",
        href: "/calls",
      },
    ],
  },
  {
    id: "experts",
    title: "For doctors and researchers",
    sub: "Be findable, ask for participants, answer patients.",
    features: [
      {
        id: "work",
        icon: Briefcase,
        title: "Work details",
        what: "Name, institutions, ORCID iD and your atlas entry. Private.",
        steps: [
          "Choose doctor or researcher when you set up (or later in Profile).",
          "Fill in Profile, Your work. Saving verifies nothing.",
        ],
        audience: "experts",
        href: "/profile#your-work",
      },
      {
        id: "card",
        icon: BadgeCheck,
        title: "Get verified, show a card",
        what: "A public card signed-in users can find, with only what you switch on.",
        steps: [
          "Confirm with ORCID, or ask for a manual review.",
          "Switch on the card and choose what it shows.",
          "Optionally accept messages from patients.",
        ],
        audience: "experts",
        href: "/profile#your-work",
      },
      {
        id: "publish",
        icon: FilePen,
        title: "Publish a call",
        what: "Invite patients to a survey, study or trial.",
        steps: [
          "Studies, New call (verified, card on).",
          "Describe it, who can take part and what to ask for.",
          "Publish lists it for every signed-in user. Calls never offer treatment.",
        ],
        audience: "experts",
        href: "/calls/mine/new",
      },
      {
        id: "received",
        icon: Users,
        title: "Sign-ups you receive",
        what: "Display name, ticked items and note. Never an e-mail or account.",
        steps: [
          "Studies, My calls, then open a call.",
          "A withdrawn sign-up shows as “withdrew”.",
        ],
        audience: "experts",
        href: "/calls/mine",
      },
    ],
  },
  {
    id: "messages",
    title: "Messages",
    sub: "Patients write first; experts accept or decline.",
    features: [
      {
        id: "write",
        icon: MessageSquare,
        title: "Write to an expert",
        what: "Start from a verified card that accepts messages.",
        steps: [
          "Find a card under “Reachable in Amber” on a disease page, or on a call.",
          "Press Message and write under a display name.",
          "It arrives as a request (up to 5 new conversations a day).",
        ],
        audience: "patients",
        href: "/messages",
      },
      {
        id: "requests",
        icon: Inbox,
        title: "Requests",
        what: "Experts see only the display name and the text.",
        steps: [
          "New requests show in Messages, with a count at the top.",
          "Accept to reply, or decline. Experts never write first.",
        ],
        audience: "experts",
        href: "/messages",
      },
      {
        id: "block",
        icon: Ban,
        title: "Block and report",
        what: "Stop a conversation or flag it for the Amber team.",
        steps: [
          "In a conversation, open its menu: Block or Report.",
          "Report one message from its own button.",
          "Unblock in Profile, Settings.",
        ],
        audience: "signed-in",
        href: "/messages",
      },
    ],
  },
];

export type TrustItem = { icon: LucideIcon; title: string; body: string };

export const TRUST: TrustItem[] = [
  { icon: Scale, title: "Information, not medical advice", body: "No diagnosis, no treatment advice. Decisions belong with your doctor." },
  { icon: UserRound, title: "What is stored", body: "Guests: nothing. Signed in: your account; health data only with your consent." },
  { icon: Users, title: "Who sees it", body: "Only you. Study teams get what you tick; experts get your display name and text." },
];

/** Every section of the page, in order, for the contents list. */
export const GUIDE_TOC = [
  ...GUIDE.map((s) => ({ id: s.id, title: s.title })),
  { id: "trust", title: "Trust and privacy" },
];
