// A full navigation (not router.replace): after an exchange the whole page renders again from the new session, with no
// router cache or in-flight transition that could leave the old report on screen. A separate module so tests can stub it.
export const goTo = (url: string) => window.location.replace(url);
