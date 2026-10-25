import React from 'react';
export default function TextField({ label, icon: Icon, type = 'text', value, onChange, placeholder, autoComplete, maxLength, trailing }) {
  return <label className="field"><span className="field-label">{label}</span><span className="input-wrap"><Icon size={19} aria-hidden="true"/><input required type={type} value={value} onChange={onChange} placeholder={placeholder} autoComplete={autoComplete} maxLength={maxLength}/>{trailing}</span></label>;
}

