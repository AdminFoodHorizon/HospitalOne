import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';
import { api } from '../../services/api';

export const fetchHospital = createAsyncThunk('hospital/fetch', async (slug, { rejectWithValue }) => {
  try {
    const response = await api.get(`/api/hospital/${encodeURIComponent(slug)}/public-info/`);
    const data = response.data;
    if (!data || data.slug !== slug || data.is_active !== true || typeof data.name !== 'string' || !data.name.trim()) throw new Error('Hospital unavailable or invalid.');
    return data;
  } catch (error) {
    return rejectWithValue(error.response?.data?.detail || 'Unable to load hospital information.');
  }
});

const hospitalSlice = createSlice({
  name: 'hospital',
  initialState: { data: null, slug: null, status: 'idle', error: null },
  reducers: {
    clearHospital(state) { state.data = null; state.slug = null; state.status = 'idle'; state.error = null; },
  },
  extraReducers: builder => builder
    .addCase(fetchHospital.pending, (state, action) => {
      state.status = 'loading'; state.slug = action.meta.arg; state.data = null; state.error = null;
    })
    .addCase(fetchHospital.fulfilled, (state, action) => {
      state.status = 'succeeded'; state.data = action.payload; state.error = null;
    })
    .addCase(fetchHospital.rejected, (state, action) => {
      state.status = 'failed'; state.data = null; state.error = action.payload || 'Request failed';
    }),
});
export const { clearHospital } = hospitalSlice.actions;
export default hospitalSlice.reducer;
