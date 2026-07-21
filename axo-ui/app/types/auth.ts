export interface AuthSession {
  access_token: string
  temporal_secret: string
  user_id: string
  username: string
  first_name: string
  last_name: string
  email: string
  profile_photo: string
}

export interface SignupPayload {
  username: string
  first_name: string
  last_name: string
  email: string
  password: string
}
