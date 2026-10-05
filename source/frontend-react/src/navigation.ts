export function loginLandingPath(today: string) {
  return `/?view=day&date=${encodeURIComponent(today)}`;
}
