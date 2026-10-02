interface FileTreeNode {
  name: string;
  fullPath: string | null; // null for directories
  children: FileTreeNode[];
}

/**
 * Build a tree from an array of "scripts/foo.sh" / "templates/x/y.txt" paths.
 * Sorts directories before files at each level for stable layout.
 */
export function buildFileTree(paths: string[]): FileTreeNode[] {
  const root: FileTreeNode = { name: '', fullPath: null, children: [] };
  for (const p of paths) {
    const parts = p.split('/').filter(Boolean);
    let cursor = root;
    for (let i = 0; i < parts.length; i++) {
      const isLeaf = i === parts.length - 1;
      const segName = parts[i];
      let child = cursor.children.find((c) => c.name === segName);
      if (!child) {
        child = {
          name: segName,
          fullPath: isLeaf ? p : null,
          children: [],
        };
        cursor.children.push(child);
      }
      cursor = child;
    }
  }
  // Sort: dirs first, then files; alphabetical within each group.
  const sortRec = (node: FileTreeNode): void => {
    node.children.sort((a, b) => {
      const aDir = a.fullPath === null;
      const bDir = b.fullPath === null;
      if (aDir !== bDir) return aDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    node.children.forEach(sortRec);
  };
  sortRec(root);
  return root.children;
}

export function FileTreeView(props: { nodes: FileTreeNode[]; onPick: (path: string) => void }) {
  // 缩进靠嵌套 ul 的固定 padding（见 css），不在 li 上写动态内联 style。
  return (
    <ul className="_memory-skill-filetree">
      {props.nodes.map((n) => (
        <li key={n.name}>
          {n.fullPath ? (
            <button
              type="button"
              onClick={() => props.onPick(n.fullPath!)}
              className="_memory-skill-file-btn"
            >
              {n.name}
            </button>
          ) : (
            <>
              <div className="_memory-skill-dir">{n.name}/</div>
              <FileTreeView nodes={n.children} onPick={props.onPick} />
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
