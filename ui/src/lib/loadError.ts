import { isApiError } from '@/lib/apiError';

export interface LoadFailure {
  text: string;
  status: number;
  signedOut: boolean;
}

/** Turn a failed API call into text that says which kind of failure it was. */
export function describeLoadError(error: unknown, subject: string): LoadFailure {
  if (isApiError(error)) {
    if (error.status === 401) {
      return { text: 'You are signed out - sign in', status: 401, signedOut: true };
    }
    if (error.status === 403) {
      return {
        text: error.message || 'You do not have permission to view this.',
        status: 403,
        signedOut: false,
      };
    }
    if (error.status === 404) {
      return {
        text: error.message || `This ${subject} was not found.`,
        status: 404,
        signedOut: false,
      };
    }
    if (error.status === 0) {
      return {
        text: 'The service did not respond. Check your connection and try again.',
        status: 0,
        signedOut: false,
      };
    }
    if (error.status >= 500) {
      return {
        text: `The service failed while loading ${subject} (HTTP ${error.status}).`,
        status: error.status,
        signedOut: false,
      };
    }
    return {
      text: error.message || `The request to load ${subject} failed.`,
      status: error.status,
      signedOut: false,
    };
  }
  return {
    text: 'The service did not respond. Check your connection and try again.',
    status: 0,
    signedOut: false,
  };
}

export function redirectIfSignedOut(failure: LoadFailure): void {
  if (!failure.signedOut || typeof window === 'undefined') return;
  window.setTimeout(() => {
    try {
      window.location.assign('/login-screen');
    } catch {
      /* jsdom and some embeds refuse navigation */
    }
  }, 0);
}

export function reportLoadError(error: unknown, subject: string): string {
  const failure = describeLoadError(error, subject);
  redirectIfSignedOut(failure);
  return failure.text;
}
