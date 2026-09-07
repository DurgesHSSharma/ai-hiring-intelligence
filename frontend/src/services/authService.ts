import { apiRequest } from "@/services/apiClient";
import type { TokenResponse, User } from "@/types";

export interface RegisterInput {
  name: string;
  email: string;
  password: string;
}

export interface LoginInput {
  email: string;
  password: string;
}

export const authService = {
  register: (input: RegisterInput) => apiRequest<User>("/auth/register", { method: "POST", body: input }),
  login: (input: LoginInput) => apiRequest<TokenResponse>("/auth/login", { method: "POST", body: input }),
  me: () => apiRequest<User>("/auth/me"),
};
