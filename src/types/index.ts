// Shared TypeScript Interface definitions for Colour Lab ERP

export interface Permission {
  id: string;
  module: string; // e.g. "orders", "payments", "dashboard", "*"
  action: string; // e.g. "create", "view", "update", "delete", "*"
}

export interface Role {
  id: string;
  name: string; // e.g. "Administrator", "Receptionist"
  description: string | null;
  is_system: boolean;
  created_at: string;
  permissions?: Permission[];
}

export interface Employee {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  department: string | null;
  designation: string | null;
  role_id: string | null;
  is_active: boolean;
  last_login: string | null;
  profile_photo_url: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  role?: Role | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface DecodedAccessToken {
  sub: string; // Employee ID
  exp: number; // Expiry timestamp
  type: string; // Token type ("access")
}

export interface ApiResponse<T = any> {
  success: boolean;
  detail?: string;
  data?: T;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}
