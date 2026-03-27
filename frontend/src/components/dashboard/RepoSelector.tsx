"use client";

import { useState, useEffect } from "react";
import { GitBranch, Lock, Globe, Search, Loader2 } from "lucide-react";
import { getToken, fetchUserRepos } from "@/lib/auth";
import {
  getSelectedRepos,
  toggleRepo as toggleRepoStore,
  subscribeRepos,
} from "@/lib/repo-store";

interface Repo {
  full_name: string;
  name: string;
  private: boolean;
  language: string | null;
  description: string | null;
  default_branch: string;
  updated_at: string;
  url: string;
  owner: string;
  permissions: Record<string, boolean>;
}

export function RepoSelector() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedRepos, setSelectedRepos] = useState<Set<string>>(
    () => new Set(getSelectedRepos()),
  );

  // Sync with store
  useEffect(() => {
    return subscribeRepos((repos) => setSelectedRepos(new Set(repos)));
  }, []);

  useEffect(() => {
    const token = getToken();
    if (!token) return;

    fetchUserRepos(token)
      .then((data) => setRepos(data.repos || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filtered = repos.filter(
    (r) =>
      r.full_name.toLowerCase().includes(search.toLowerCase()) ||
      (r.description || "").toLowerCase().includes(search.toLowerCase()),
  );

  const toggleRepo = (fullName: string) => {
    toggleRepoStore(fullName);
  };

  const langColors: Record<string, string> = {
    TypeScript: "bg-blue-500",
    JavaScript: "bg-yellow-500",
    Python: "bg-green-500",
    Go: "bg-cyan-500",
    Rust: "bg-orange-500",
    Java: "bg-red-500",
    Ruby: "bg-red-400",
  };

  return (
    <div className="p-6 overflow-y-auto h-full">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-primary" />
            Your Repositories
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Select repositories for the AI agents to analyze
          </p>
        </div>
        {selectedRepos.size > 0 && (
          <span className="px-3 py-1 rounded-full bg-primary text-primary-foreground text-sm">
            {selectedRepos.size} selected
          </span>
        )}
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search repositories..."
          className="w-full pl-10 pr-4 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-muted-foreground py-8 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Loading your repositories from GitHub...</span>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((repo) => {
            const selected = selectedRepos.has(repo.full_name);
            return (
              <button
                key={repo.full_name}
                onClick={() => toggleRepo(repo.full_name)}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  selected
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-primary/50 hover:bg-accent"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {repo.private ? (
                      <Lock className="h-4 w-4 text-yellow-500" />
                    ) : (
                      <Globe className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className="font-medium text-sm">{repo.full_name}</span>
                  </div>

                  <div className="flex items-center gap-2">
                    {repo.language && (
                      <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        <span
                          className={`w-2 h-2 rounded-full ${langColors[repo.language] || "bg-gray-400"}`}
                        />
                        {repo.language}
                      </span>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {repo.default_branch}
                    </span>
                  </div>
                </div>

                {repo.description && (
                  <p className="text-xs text-muted-foreground mt-1 ml-6">
                    {repo.description}
                  </p>
                )}
              </button>
            );
          })}

          {filtered.length === 0 && !loading && (
            <p className="text-center text-muted-foreground py-8">
              {search ? "No repos match your search" : "No repositories found"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
