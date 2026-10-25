export function extractUri(data) {
  return data?.otpauth_uri || data?.provisioning_uri || data?.otpauth_url || data?.otp_uri || data?.uri || data?.setup_uri || '';
}
export function extractSecret(data) {
  const explicit = data?.secret || data?.manual_key || data?.totp_secret;
  if (explicit) return explicit;
  const uri = extractUri(data);
  if (!uri) return '';
  try {
    const url = new URL(uri);
    return url.protocol === 'otpauth:' ? url.searchParams.get('secret') || '' : '';
  } catch { return ''; }
}
