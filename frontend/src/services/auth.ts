import type {
  TokenResponse,
  UserCreate,
  UserLogin,
  UserResponse,
} from "../types";
import { api } from "./api.ts";

const TOKEN_KEY = "anti_proxy_access_token";
const USER_KEY = "anti_proxy_user";
const MUST_CHANGE_KEY = "anti_proxy_must_change_password";

class MemoryStorage {
  private store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  clear(): void {
    this.store.clear();
  }
}

const memoryStorage = new MemoryStorage();

function getStorage(): Storage | MemoryStorage {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // In restricted iframe or non-browser environments
  }
  return memoryStorage;
}

export function getStoredToken(): string | null {
  return getStorage().getItem(TOKEN_KEY);
}

export function getStoredUser(): UserResponse | null {
  const raw = getStorage().getItem(USER_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as UserResponse;
  } catch {
    getStorage().removeItem(USER_KEY);
    return null;
  }
}

export function setStoredAuth(token: string, user: UserResponse): void {
  const storage = getStorage();
  storage.setItem(TOKEN_KEY, token);
  storage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearStoredAuth(): void {
  const storage = getStorage();
  storage.removeItem(TOKEN_KEY);
  storage.removeItem(USER_KEY);
  storage.removeItem(MUST_CHANGE_KEY);
}

// Whether the signed-in account has to choose a new password before anything else.
export function mustChangePassword(): boolean {
  return getStorage().getItem(MUST_CHANGE_KEY) === "1";
}

export function setMustChangePassword(required: boolean): void {
  if (required) {
    getStorage().setItem(MUST_CHANGE_KEY, "1");
  } else {
    getStorage().removeItem(MUST_CHANGE_KEY);
  }
}

export function isAuthenticated(): boolean {
  return Boolean(getStoredToken());
}

export async function login(credentials: UserLogin): Promise<TokenResponse> {
  const response = await api.login(credentials);
  setStoredAuth(response.access_token, response.user);
  setMustChangePassword(Boolean(response.must_change_password));
  return response;
}

// Every earlier token stops working; the new one replaces the stored token.
export async function changePassword(currentPassword: string, newPassword: string): Promise<TokenResponse> {
  const response = await api.changePassword(currentPassword, newPassword);
  setStoredAuth(response.access_token, response.user);
  setMustChangePassword(Boolean(response.must_change_password));
  return response;
}

export async function register(userData: UserCreate): Promise<UserResponse> {
  return api.register(userData);
}

export function logout(): void {
  clearStoredAuth();
}

export const auth = {
  login,
  changePassword,
  mustChangePassword,
  setMustChangePassword,
  register,
  logout,
  getStoredUser,
  getStoredToken,
  setStoredAuth,
  clearStoredAuth,
  isAuthenticated,
};
