/**
 * Frozen prop types for the Atlas children built in parallel (search,
 * outline, panel, Dr. Wu dock) and the shared types they need. `AtlasView`
 * owns the state (selection, shown chain, Dr. Wu's finds) and wires these
 * components; each component reads the lens itself via `useLens()`.
 *
 * Privacy (docs/compliance.md): free text and Dr. Wu's finds stay in React
 * state only — never in the URL, storage, logs or analytics.
 */
import type { TreeIndex } from "./tree-model";

/** Options for selecting a node on the Atlas. */
export type SelectOptions = {
  /** Move the camera to the node (groups: frame the whole subtree). Default false. */
  center?: boolean;
  /** Write `?focus=<id>` to the URL. Default true; false for anything Dr. Wu found. */
  persist?: boolean;
};

/** Select a tree node (entity or group) by id, or clear the selection with `null`. */
export type AtlasSelect = (id: string | null, options?: SelectOptions) => void;

/** What Dr. Wu found in his last final reply. */
export type WuFound = {
  /** Entity ids on the map from `graph_focus.node_ids`, `cards[].node_ids` and chips, deduplicated, in reply order (ringed and framed). */
  nodeIds: string[];
  /** Real edge ids from `graph_focus.highlight_path`, in path order (may be empty). */
  edgeIds: string[];
  /**
   * Every found id in reply order, on the map or not (nodes that exist but are not in the tree,
   * e.g. core diseases). The dock lists and counts these. Absent: the same as `nodeIds`.
   */
  allIds?: string[];
};

/** Search combobox centred at the top of the canvas (`data-testid="atlas-search"`). */
export type AtlasSearchProps = {
  /** Tree index for local matches over all tree nodes (groups included) and breadcrumbs. */
  index: TreeIndex;
  /** A local or server match was picked; the view selects it and frames it when it is on the map (groups: the subtree). */
  onPick: (id: string) => void;
  /** Free text that is not an entity query was handed to Dr. Wu ("Ask Dr. Wu"); in memory only. */
  onAskWu: (text: string) => void;
  /** Extra classes for positioning by the view. */
  className?: string;
};

/** Accessible treeview alternative to the canvas, shown via the graph/list `ViewToggle` (`data-testid="atlas-outline"`). */
export type AtlasOutlineProps = {
  /** Tree index to render (all nodes; the outline may collapse groups, the graph never does). */
  index: TreeIndex;
  /** Currently selected node id, highlighted and expanded-to; null when nothing is selected. */
  selectedId: string | null;
  /** A tree item was activated (Enter / click); the view selects it. */
  onSelect: (id: string) => void;
  /** Extra classes for layout by the view. */
  className?: string;
};

/** Right-hand summary panel, bottom sheet on mobile (`data-testid="atlas-panel"`). */
export type AtlasPanelProps = {
  /** Tree index: node lookup, breadcrumb (ancestors) and local group panels. */
  index: TreeIndex;
  /** Selected node: an entity (summary from `getAtlasSummary`), a `T:` group (local panel), or null ("Search or click a dot"). */
  nodeId: string | null;
  /** Select another node (summary item, breadcrumb crumb or group child); the view selects and centres it. */
  onSelect: (id: string) => void;
  /** Draw a chain of real edge ids on the map (a summary item's `via`); an empty array clears it. */
  onShowChain: (edgeIds: string[]) => void;
  /** Close the panel; the view clears the selection. */
  onClose: () => void;
  /** The selected id is not in the tree and the summary says it does not exist (404). */
  onMissing?: (id: string) => void;
  /** Extra classes for positioning by the view. */
  className?: string;
};

/** Dr. Wu dock, a floating card bottom-left, a Sheet on mobile (`data-testid="atlas-wu-dock"`). */
export type AtlasWuDockProps = {
  /** Tree index, to tell found ids on the map from those that are not, and to label them. */
  index: TreeIndex;
  /** Question handed over from the search bar, or null; the dock puts it into its composer (it is not sent automatically). */
  pendingQuestion: string | null;
  /** The dock has taken `pendingQuestion`; the view resets it to null. */
  onPendingConsumed: () => void;
  /** Current finds, owned by the view (rings and frames them on the map); null when none. */
  found: WuFound | null;
  /** Report the finds of a new final reply; the view stores them in state only. */
  onFound: (found: WuFound) => void;
  /** Clear the finds ("Dr. Wu found N" chip clear button). */
  onClear: () => void;
  /** Select a found node; always call as `onSelect(id, { center: true, persist: false })`. */
  onSelect: AtlasSelect;
  /** Extra classes for positioning by the view. */
  className?: string;
};
