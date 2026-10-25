import React from 'react';
import { Activity, ArrowRight, Building2, HeartPulse, Mail, MapPin, Phone, ShieldCheck, Stethoscope, Users, Globe } from 'lucide-react';
import './HospitalHome.css';

const features = [
  { icon: Users, title: 'Patient-Centered Care', description: 'A welcoming environment focused on patients and their care journey.' },
  { icon: HeartPulse, title: 'Coordinated Care', description: 'Connected hospital teams supporting efficient patient workflows.' },
  { icon: ShieldCheck, title: 'Secure Staff Access', description: 'Protected access for authorized hospital staff.' },
  { icon: Stethoscope, title: 'Clinical Workflows', description: 'Digital tools supporting everyday hospital operations.' },
];

export default function HospitalHome({ hospital }) {
  if (!hospital) return null;
  const branding = hospital.branding || {};
  const contact = hospital.contact || {};
  const home = `/hospital/${encodeURIComponent(hospital.slug)}/`;
  const login = `${home}login`;
  return <div className="hh-page">
    <header className="hh-header"><div className="hh-container hh-header-inner">
      <a className="hh-brand" href={home}>{branding.logo_url ? <img className="hh-logo" src={branding.logo_url} alt={`${hospital.name} logo`}/> : <span className="hh-logo-fallback"><Building2/></span>}<span className="hh-brand-text"><strong>{hospital.name}</strong>{branding.tagline && <small>{branding.tagline}</small>}</span></a>
      <nav className="hh-nav" aria-label="Main navigation"><a href={home}>Home</a><a href="#contact">Contact</a><a className="hh-nav-login" href={login}>Staff Portal <ArrowRight size={16}/></a></nav>
    </div></header>
    <main><section className="hh-hero">
      {branding.banner_url && <img className="hh-hero-image" src={branding.banner_url} alt={`${hospital.name} banner`}/>}
      <div className="hh-hero-overlay"/><div className="hh-container hh-hero-content"><span className="hh-eyebrow"><Activity size={16}/> Welcome to our hospital</span><h1>{hospital.name}</h1>{branding.tagline && <h2>{branding.tagline}</h2>}<p>{branding.welcome_message || 'Welcome to our hospital. Access our secure staff portal to manage hospital workflows.'}</p><a className="hh-primary-button" href={login}>Access Staff Portal <ArrowRight size={19}/></a></div>
    </section><section className="hh-features"><div className="hh-container"><div className="hh-section-heading"><span>HOSPITAL OPERATIONS</span><h2>Supporting Better Care</h2><p>A connected digital experience for hospital teams and day-to-day operations.</p></div><div className="hh-feature-grid">{features.map(item => { const Icon = item.icon; return <article className="hh-feature-card" key={item.title}><div className="hh-feature-icon"><Icon size={25}/></div><h3>{item.title}</h3><p>{item.description}</p></article>; })}</div></div></section>
    <section className="hh-portal-section"><div className="hh-container hh-portal-inner"><div><span className="hh-portal-label">STAFF ACCESS</span><h2>Hospital Staff Portal</h2><p>Authorized hospital staff can securely sign in to access their assigned dashboard.</p></div><a className="hh-secondary-button" href={login}>Staff Login <ArrowRight size={18}/></a></div></section></main>
    <footer className="hh-footer" id="contact"><div className="hh-container hh-footer-grid"><div><div className="hh-footer-brand">{branding.logo_url ? <img src={branding.logo_url} alt={`${hospital.name} logo`}/> : <Building2 size={29}/>}<strong>{hospital.name}</strong></div>{branding.footer_description && <p>{branding.footer_description}</p>}</div><div><h3>Quick Links</h3><a href={home}>Home</a><a href={login}>Staff Portal</a><a href="#contact">Contact</a></div><div><h3>Contact Information</h3>{contact.address && <p className="hh-contact-line"><MapPin size={18}/><span>{contact.address}</span></p>}{contact.phone && <a className="hh-contact-line" href={`tel:${contact.phone}`}><Phone size={18}/><span>{contact.phone}</span></a>}{contact.email && <a className="hh-contact-line" href={`mailto:${contact.email}`}><Mail size={18}/><span>{contact.email}</span></a>}{contact.website && <a className="hh-contact-line" href={contact.website} target="_blank" rel="noopener noreferrer"><Globe size={18}/><span>Official Website</span></a>}{!contact.address && !contact.phone && !contact.email && !contact.website && <p>Contact details will be available here when provided by the hospital.</p>}</div></div><div className="hh-footer-bottom"><div className="hh-container"><span>© {new Date().getFullYear()} {hospital.name}</span><span>Private hospital workspace</span></div></div></footer>
  </div>;
}
