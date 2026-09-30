export type UserRole = 'TEACHER' | 'STUDENT' | 'ADMIN';

export interface UserCreate {
  email: string;
  password: string;
  role: 'TEACHER' | 'STUDENT';
}

export interface UserLogin {
  email: string;
  password: string;
}

export interface UserResponse {
  user_id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserResponse;
}
