import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import { User } from "@/types/auth";

interface AuthState {
  isAuthenticated: boolean;
  isInitialized: boolean;
  isSessionExpired: boolean;
  user: User | null;
  error: string | null;
}

const initialState: AuthState = {
  isAuthenticated: false,
  isInitialized: false,
  isSessionExpired: false,
  user: null,
  error: null,
};

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    signInSuccess(state, action: PayloadAction<User>) {
      state.isAuthenticated = true;
      state.isInitialized = true;
      state.isSessionExpired = false;
      state.user = action.payload;
      state.error = null;
    },
    signOut(state) {
      state.isAuthenticated = false;
      state.isInitialized = true;
      state.isSessionExpired = false;
      state.user = null;
      state.error = null;
    },
    sessionExpired(state) {
      state.isAuthenticated = false;
      state.isSessionExpired = true;
      state.user = null;
      state.error = null;
    },
    setAuthError(state, action: PayloadAction<string | null>) {
      state.error = action.payload;
    },
    setInitialized(state, action: PayloadAction<boolean>) {
      state.isInitialized = action.payload;
    },
  },
});

export const {
  signInSuccess,
  signOut,
  sessionExpired,
  setAuthError,
  setInitialized,
} = authSlice.actions;

export default authSlice.reducer;
