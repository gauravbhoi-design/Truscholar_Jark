const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface AuthUser {
  login: string;
  name: string;
  email: string | null;
  avatar_url: string | null;
  role: string;
}

export interface AuthState {
  token: string | null;
  user: AuthUser | null;
}

/**
 * Get the GitHub OAuth login URL from the backend.
 */
export async function getGitHubLoginUrl(): Promise<string> {
  const res = await fetch(`${API_URL}/auth/github/login`);
  const data = await res.json();
  return data.authorize_url;
}

/**
 * Get the Google OAuth login URL from the backend.
 */
export async function getGoogleLoginUrl(): Promise<string> {
  const res = await fetch(`${API_URL}/auth/google/login`);
  if (!res.ok) return "";
  const data = await res.json();
  return data.authorize_url;
}

/**
 * Get the current user's profile using the stored JWT.
 */
export async function fetchCurrentUser(token: string): Promise<AuthUser> {
  const res = await fetch(`${API_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Not authenticated");
  return res.json();
}

/**
 * Get user's GitHub repositories.
 */
export async function fetchUserRepos(token: string) {
  const res = await fetch(`${API_URL}/auth/repos`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch repos");
  return res.json();
}

/**
 * Store auth token in localStorage.
 */
export function saveToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem("copilot_token", token);
  }
}

/**
 * Get stored auth token.
 */
export function getToken(): string | null {
  if (typeof window !== "undefined") {
    return localStorage.getItem("copilot_token");
  }
  return null;
}

/**
 * Clear auth state (logout).
 */
export function logout(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("copilot_token");
    window.location.href = "/";
  }
}
