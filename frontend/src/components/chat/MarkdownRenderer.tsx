"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

const components: Components = {
  // ─── Tables ───────────────────────────────────────────
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-xs border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-muted/50">{children}</thead>
  ),
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => (
    <tr className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors">
      {children}
    </tr>
  ),
  th: ({ children }) => (
    <th className="px-3 py-2 text-left font-semibold text-foreground whitespace-nowrap">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-3 py-2 text-muted-foreground">{children}</td>
  ),

  // ─── Headings ─────────────────────────────────────────
  h1: ({ children }) => (
    <h1 className="text-xl font-bold mt-5 mb-3 text-foreground border-b border-border pb-2">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-lg font-bold mt-4 mb-2 text-foreground flex items-center gap-2">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-sm font-bold mt-3 mb-1.5 text-foreground">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="text-sm font-semibold mt-2 mb-1 text-foreground">{children}</h4>
  ),

  // ─── Code ─────────────────────────────────────────────
  code: ({ className, children, ...props }) => {
    const isBlock = className?.includes("language-");
    const lang = className?.replace("language-", "");

    // ASCII tree blocks get a dedicated "folder structure" style with
    // whitespace-pre so Unicode box-drawing chars align correctly.
    if (isBlock && lang === "tree") {
      return (
        <div className="my-3 rounded-lg overflow-hidden border border-border">
          <div className="flex items-center gap-1.5 px-3 py-1.5 bg-muted/50 border-b border-border">
            <svg className="h-3 w-3 text-muted-foreground" viewBox="0 0 16 16" fill="currentColor">
              <path d="M1 3.5A1.5 1.5 0 0 1 2.5 2h3.879a1.5 1.5 0 0 1 1.06.44l1.122 1.12A1.5 1.5 0 0 0 9.62 4H13.5A1.5 1.5 0 0 1 15 5.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 12.5v-9z" />
            </svg>
            <span className="text-[10px] font-mono text-muted-foreground">folder structure</span>
          </div>
          <pre className="p-3 overflow-x-auto bg-muted/20 whitespace-pre leading-relaxed">
            <code className="text-xs font-mono text-foreground" {...props}>
              {children}
            </code>
          </pre>
        </div>
      );
    }

    if (isBlock) {
      return (
        <div className="my-3 rounded-lg overflow-hidden border border-border">
          <div className="flex items-center px-3 py-1.5 bg-muted/50 border-b border-border">
            <span className="text-[10px] font-mono text-muted-foreground">
              {lang || "code"}
            </span>
          </div>
          <pre className="p-3 overflow-x-auto bg-muted/20">
            <code className="text-xs font-mono text-foreground" {...props}>
              {children}
            </code>
          </pre>
        </div>
      );
    }
    return (
      <code
        className="px-1.5 py-0.5 rounded bg-muted text-primary text-xs font-mono"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children }) => <>{children}</>,

  // ─── Lists ────────────────────────────────────────────
  ul: ({ children }) => (
    <ul className="my-2 ml-4 space-y-1 list-disc text-sm text-muted-foreground marker:text-primary/50">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-2 ml-4 space-y-1 list-decimal text-sm text-muted-foreground marker:text-primary/50">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="text-sm leading-relaxed">{children}</li>,

  // ─── Paragraphs & text ────────────────────────────────
  p: ({ children }) => (
    <p className="my-2 text-sm leading-relaxed text-foreground">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-muted-foreground">{children}</em>
  ),

  // ─── Links ────────────────────────────────────────────
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline underline-offset-2 hover:text-primary/80"
    >
      {children}
    </a>
  ),

  // ─── Blockquotes ──────────────────────────────────────
  blockquote: ({ children }) => (
    <blockquote className="my-3 pl-3 border-l-2 border-primary/30 text-muted-foreground italic">
      {children}
    </blockquote>
  ),

  // ─── Horizontal rule ──────────────────────────────────
  hr: () => <hr className="my-4 border-border" />,

  // ─── Images ───────────────────────────────────────────
  img: ({ src, alt }) => (
    <img
      src={src}
      alt={alt || ""}
      className="my-3 rounded-lg max-w-full border border-border"
    />
  ),
};

interface Props {
  content: string;
}

export function MarkdownRenderer({ content }: Props) {
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
