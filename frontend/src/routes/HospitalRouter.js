
import React, { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { fetchHospital } from '../features/hospital/hospitalSlice';

import HospitalHome from '../pages/HospitalHome';
import StaffAuth from '../features/auth/StaffAuth';
import AnnouncementScreen from '../pages/AnnouncementScreen';
import DisplayPairingApproval from '../pages/DisplayPairingApproval';


function parseHospitalRoute() {
  const match = window.location.pathname.match(
    /^\/hospital\/([a-z0-9-]+)(?:\/(login|announcements|display-approval))?\/?$/
  );

  if (!match) {
    return null;
  }

  return {
    slug: match[1],
    isLogin: match[2] === 'login',
    isAnnouncement: match[2] === 'announcements',
    isDisplayApproval: match[2] === 'display-approval',
  };
}


export default function HospitalRouter() {
  const route = parseHospitalRoute();

  const dispatch = useDispatch();

  const {
    data,
    slug,
    status,
    error,
  } = useSelector((state) => state.hospital);

  const routeSlug = route?.slug;

  useEffect(() => {
    if (routeSlug) {
      dispatch(fetchHospital(routeSlug));
    }
  }, [dispatch, routeSlug]);

  if (!route) {
    return (
      <main className="hospital-route-error">
        <div className="hospital-route-error-card">
          <h1>Hospital link required</h1>
          <p>
            Use your hospital homepage, staff login,
            announcement screen, or TV approval URL.
          </p>
        </div>
      </main>
    );
  }

  if (
    status === 'idle' ||
    status === 'loading' ||
    slug !== route.slug
  ) {
    return (
      <main className="hospital-route-error">
        <div className="hospital-route-error-card">
          <h1>Loading hospital workspace…</h1>
        </div>
      </main>
    );
  }

  if (status === 'failed' || !data) {
    return (
      <main className="hospital-route-error">
        <div className="hospital-route-error-card">
          <h1>Hospital unavailable</h1>
          <p role="alert">
            {error || 'Unable to load this hospital.'}
          </p>
        </div>
      </main>
    );
  }

  // Central Announcement TV
  if (route.isAnnouncement) {
    return (
      <AnnouncementScreen
        hospital={data}
        hospitalSlug={route.slug}
      />
    );
  }

  // Hospital administrator TV approval
  if (route.isDisplayApproval) {
    return (
      <DisplayPairingApproval
        hospital={data}
        hospitalSlug={route.slug}
      />
    );
  }

  // Existing staff login
  if (route.isLogin) {
    return <StaffAuth hospital={data} />;
  }

  // Existing hospital homepage
  return <HospitalHome hospital={data} />;
}
