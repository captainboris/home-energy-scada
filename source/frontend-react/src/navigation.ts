export function loginLandingPath(today: string) {
  return `/?view=day&date=${encodeURIComponent(today)}`;
}

export function replaceLoginLanding(today: string) {
  window.location.replace(loginLandingPath(today));
}
