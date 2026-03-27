/**
 * Centralized repo selection store with cross-component sync.
 * Replaces raw localStorage access scattered across components.
 */

type Listener = (repos: string[]) => void;

const listeners = new Set<Listener>();
const STORAGE_KEY = "selected_repos";

function read(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch {
    return [];
  }
}

function write(repos: string[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(repos));
  listeners.forEach((fn) => fn(repos));
}

export function getSelectedRepos(): string[] {
  return read();
}

export function setSelectedRepos(repos: string[]): void {
  write(repos);
}

export function toggleRepo(fullName: string): string[] {
  const current = read();
  const next = current.includes(fullName)
    ? current.filter((r) => r !== fullName)
    : [...current, fullName];
  write(next);
  return next;
}

export function removeRepo(fullName: string): string[] {
  const next = read().filter((r) => r !== fullName);
  write(next);
  return next;
}

export function clearRepos(): string[] {
  write([]);
  return [];
}

export function subscribeRepos(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
