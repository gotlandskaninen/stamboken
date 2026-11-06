export interface User {
  id?: string; // Unique identifier
  email: string | null;
  username: string | null;
  validated: boolean;
  fullname: string | null;
  is_admin: boolean;
  is_manager: number[] | null; // Array of Genebank IDs the user manages
  is_owner: string[] | null; // Array of Herd IDs the user owns
  // Profile pictures
  profile_picture?: string | null; // Custom uploaded picture path
  google_picture?: string | null; // Google profile picture URL
  google_name?: string | null; // Google display name
  google_email?: string | null; // Google email (might differ from main email)
  use_google_picture?: boolean; // User preference for using Google picture
}

// Redux auth state type
export interface AuthState {
  isAuthenticated: boolean;
  isInitialized: boolean;
  user: User | null;
  error: string | null;
}

// Legacy types for backward compatibility (if needed)
export type AuthUser = User | null;
