'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import AppLogo from '@/components/ui/AppLogo';
import ToastHost from '@/components/ui/Toast';
import { api } from '@/lib/apiClient';
import { redirectForSetup } from '@/lib/setupRedirect';
import { DEMO_ACCOUNTS, type DemoAccount } from '@/lib/mock/mockAuth';
import BrandPanel from './BrandPanel';
import CredentialsBox from './CredentialsBox';

interface LoginForm {
  email: string;
  password: string;
  remember: boolean;
}

export default function LoginScreenView() {
  const router = useRouter();
  const [show, setShow] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<LoginForm>({ defaultValues: { email: '', password: '', remember: true } });

  // The first-run setup page is served separately: send the browser there if setup is not complete.
  useEffect(() => {
    api
      .getSetupState()
      .then((state) => {
        const target = redirectForSetup(state, window.location.pathname);
        if (target) window.location.assign(target);
      })
      .catch(() => undefined);
  }, []);

  const onSubmit = async (v: LoginForm) => {
    setFormError(null);
    setSubmitting(true);
    // BACKEND: POST /api/v1/auth/login
    const res = await api.login(v.email, v.password);
    setSubmitting(false);
    if (!res.ok) {
      setFormError(res.error ?? 'Invalid credentials.');
      return;
    }
    toast.success(`Signed in as ${res.role}`);
    router.push('/');
  };

  const fill = (a: DemoAccount) => {
    setValue('email', a.email, { shouldValidate: true });
    setValue('password', a.password, { shouldValidate: true });
    setFormError(null);
  };

  return (
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[1.1fr_1fr]">
      <BrandPanel />

      <main className="flex items-center justify-center bg-background px-5 py-10 sm:px-10">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <AppLogo size={40} />
            <span className="text-lg font-semibold tracking-tight">InsightEngine</span>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight">Sign in to your network</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            See which device and port is broken, and since when.
          </p>

          <button
            type="button"
            onClick={() =>
              toast.info(
                'SSO redirect would start here (identity provider not connected in this mock).'
              )
            }
            className="mt-6 flex h-10 w-full items-center justify-center gap-2 rounded-md border border-border bg-card text-sm font-medium transition-all hover:bg-muted active:scale-[0.98]"
          >
            <Icon name="IdentificationIcon" size={18} />
            Continue with company SSO
          </button>

          <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            or use your email
            <span className="h-px flex-1 bg-border" />
          </div>

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
            {formError && (
              <div
                role="alert"
                className="slide-up flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
              >
                <Icon
                  name="ExclamationCircleIcon"
                  size={18}
                  variant="solid"
                  className="mt-0.5 shrink-0"
                />
                {formError}
              </div>
            )}

            <div>
              <label htmlFor="email" className="text-sm font-medium">
                Work email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                aria-invalid={!!errors.email}
                {...register('email', {
                  required: 'Enter your work email',
                  pattern: {
                    value: /^\S+@\S+\.\S+$/,
                    message: 'Enter a valid email address, like name@company.example',
                  },
                })}
                className={`mt-1.5 h-10 w-full rounded-md border bg-card px-3 text-sm outline-none transition-colors focus:border-ring ${errors.email ? 'border-destructive' : 'border-input'}`}
              />
              {errors.email && (
                <p className="mt-1 text-xs text-destructive">{errors.email.message}</p>
              )}
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="password" className="text-sm font-medium">
                  Password
                </label>
                <button
                  type="button"
                  onClick={() =>
                    toast.info('Password reset links are sent by your administrator in this mock.')
                  }
                  className="text-xs font-medium text-primary hover:underline"
                >
                  Forgot password?
                </button>
              </div>
              <div className="relative mt-1.5">
                <input
                  id="password"
                  type={show ? 'text' : 'password'}
                  autoComplete="current-password"
                  aria-invalid={!!errors.password}
                  {...register('password', {
                    required: 'Enter your password',
                    minLength: { value: 8, message: 'Passwords have at least 8 characters' },
                  })}
                  className={`h-10 w-full rounded-md border bg-card pl-3 pr-10 text-sm outline-none transition-colors focus:border-ring ${errors.password ? 'border-destructive' : 'border-input'}`}
                />
                <button
                  type="button"
                  onClick={() => setShow((v) => !v)}
                  aria-label={show ? 'Hide password' : 'Show password'}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                >
                  <Icon name={show ? 'EyeSlashIcon' : 'EyeIcon'} size={18} />
                </button>
              </div>
              {errors.password && (
                <p className="mt-1 text-xs text-destructive">{errors.password.message}</p>
              )}
            </div>

            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                {...register('remember')}
                className="h-4 w-4 accent-[var(--primary)]"
              />
              Keep me signed in on this device
            </label>

            <button
              type="submit"
              disabled={submitting}
              className="flex h-10 w-full items-center justify-center gap-2 rounded-md bg-navy text-sm font-semibold text-primary-foreground transition-all hover:bg-navy-2 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-80"
            >
              {submitting ? (
                <Icon name="ArrowPathIcon" size={16} className="animate-spin" />
              ) : (
                <Icon name="ArrowRightEndOnRectangleIcon" size={16} />
              )}
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {DEMO_ACCOUNTS.length > 0 ? (
            <CredentialsBox accounts={DEMO_ACCOUNTS} onUse={fill} />
          ) : null}

          <p className="mt-6 text-center text-xs text-muted-foreground">
            By signing in you agree to the{' '}
            <a href="#terms" className="underline hover:text-foreground">
              Terms of service
            </a>{' '}
            and{' '}
            <a href="#privacy" className="underline hover:text-foreground">
              Privacy policy
            </a>
            .
          </p>
          <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-[11px] text-muted-foreground">
            <Icon name="WrenchScrewdriverIcon" size={12} />
            First-run setup is a separate page at <span className="font-mono-data">/setup/</span>;
            this screen redirects there until setup is complete.
          </p>
        </div>
      </main>
      <ToastHost />
    </div>
  );
}
