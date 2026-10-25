import { createSlice } from '@reduxjs/toolkit';
// Only the verified staff profile is stored in memory. Never store passwords,
// authenticator setup secrets, OTPs, recovery codes or patient records here.
const authSlice = createSlice({
  name: 'auth',
  initialState: { profile: null },
  reducers: {
    setAuthenticatedProfile(state, action) { state.profile = action.payload; },
    clearAuth(state) { state.profile = null; },
  },
});
export const { setAuthenticatedProfile, clearAuth } = authSlice.actions;
export default authSlice.reducer;
