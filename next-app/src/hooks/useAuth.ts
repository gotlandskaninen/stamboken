import { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import {
  useLoginMutation,
  useLogoutMutation,
  useFetchUserQuery,
  useGoogleLoginMutation,
} from "@/redux/api/apiSlice";
import { RootState, AppDispatch } from "@/redux/store";
import {
  signInSuccess,
  signOut,
  setAuthError,
  setInitialized,
} from "@/redux/slices/authSlice";

const useAuth = (skipUserFetch: boolean = false) => {
  const dispatch = useDispatch<AppDispatch>();
  const { isAuthenticated, isInitialized, user, error } = useSelector(
    (state: RootState) => state.auth,
  );

  // RTK Query hooks
  const [login, { isLoading: isLoggingIn }] = useLoginMutation();
  const [googleLogin, { isLoading: isGoogleLoggingIn }] =
    useGoogleLoginMutation();
  const [logout, { isLoading: isLoggingOut }] = useLogoutMutation();
  const {
    data: fetchedUser,
    isSuccess: isUserFetched,
    isError: isUserFetchError,
  } = useFetchUserQuery(undefined, {
    skip: skipUserFetch, // Skip the query if not needed
  });

  // Initialize authentication state by fetching the current user
  useEffect(() => {
    if (isUserFetched && fetchedUser) {
      dispatch(signInSuccess(fetchedUser));
    } else if (isUserFetched && !fetchedUser) {
      dispatch(signOut());
    } else if (isUserFetchError) {
      dispatch(setInitialized(true));
    }
  }, [isUserFetched, fetchedUser, isUserFetchError, dispatch]);

  // Sign In function
  const signIn = async (username: string, password: string) => {
    try {
      const result = await login({ username, password }).unwrap();
      dispatch(signInSuccess(result));
    } catch (err: any) {
      const message = err?.data?.message || "Failed to sign in";
      dispatch(setAuthError(message));
      throw new Error(message);
    }
  };

  // Google Sign In function
  const signInWithGoogle = async (credential: string) => {
    try {
      const result = await googleLogin({ credential }).unwrap();
      dispatch(signInSuccess(result));
    } catch (err: any) {
      const message = err?.data?.message || "Failed to sign in with Google";
      dispatch(setAuthError(message));
      throw new Error(message);
    }
  };

  // Sign Out function
  const signOutUser = async () => {
    try {
      await logout().unwrap();
      dispatch(signOut());
    } catch (err) {
      console.error("Failed to sign out:", err);
    }
  };

  return {
    isAuthenticated,
    isInitialized,
    user,
    error,
    isLoggingIn: isLoggingIn || isGoogleLoggingIn,
    isLoggingOut,
    signIn,
    signInWithGoogle,
    signOut: signOutUser,
  };
};

export default useAuth;
