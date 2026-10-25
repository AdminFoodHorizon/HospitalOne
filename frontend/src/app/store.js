
import { configureStore } from '@reduxjs/toolkit';

import hospitalReducer from '../features/hospital/hospitalSlice';
import authReducer from '../features/auth/authSlice';

export const store = configureStore({
  reducer: {
    hospital: hospitalReducer,
    auth: authReducer,
  },
});
