import { describe, it, expect } from "vitest";
import { User } from "@/types/auth";
import authReducer, {
  signInSuccess,
  signOut,
  sessionExpired,
  setAuthError,
} from "@/redux/slices/authSlice";

const mockUser: User = {
  id: "1",
  email: "test@gotlandskaninen.se",
  username: "test",
  validated: true,
  fullname: "Test User",
  is_admin: false,
  is_manager: [],
  is_owner: [],
  profile_picture: null,
  google_picture: null,
  google_name: null,
  google_email: null,
  use_google_picture: true,
};

describe("authSlice", () => {
  it("handles sessionExpired — clears user and sets flag", () => {
    // Start authenticated
    const authenticated = authReducer(undefined, signInSuccess(mockUser));
    expect(authenticated.isAuthenticated).toBe(true);
    expect(authenticated.isSessionExpired).toBe(false);

    // Session expires
    const expired = authReducer(authenticated, sessionExpired());
    expect(expired.isAuthenticated).toBe(false);
    expect(expired.isSessionExpired).toBe(true);
    expect(expired.user).toBeNull();
  });

  it("signInSuccess clears sessionExpired flag", () => {
    // Start with expired session
    const expired = authReducer(undefined, sessionExpired());
    expect(expired.isSessionExpired).toBe(true);

    // Sign in again
    const signedIn = authReducer(expired, signInSuccess(mockUser));
    expect(signedIn.isAuthenticated).toBe(true);
    expect(signedIn.isSessionExpired).toBe(false);
  });

  it("signOut clears sessionExpired flag", () => {
    const expired = authReducer(undefined, sessionExpired());
    const loggedOut = authReducer(expired, signOut());
    expect(loggedOut.isSessionExpired).toBe(false);
  });

  it("setAuthError does not affect sessionExpired", () => {
    const expired = authReducer(undefined, sessionExpired());
    const withError = authReducer(expired, setAuthError("some error"));
    expect(withError.isSessionExpired).toBe(true);
    expect(withError.error).toBe("some error");
  });
});
