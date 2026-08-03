import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Link, useNavigate } from 'react-router-dom';
import { useNotificationStore } from '../../app/store';
import { authService } from '../../services/auth';
import { Loader2, Mail, ArrowLeft, Key } from 'lucide-react';

const forgotSchema = z.object({
  email: z.string().trim().min(1, 'Email is required').email('Invalid email address'),
});

type ForgotFormValues = z.infer<typeof forgotSchema>;

export default function ForgotPassword() {
  const navigate = useNavigate();
  const { addToast } = useNotificationStore();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [resetToken, setResetToken] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotFormValues>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: '' },
  });

  const onSubmit = async (data: ForgotFormValues) => {
    setIsSubmitting(true);
    try {
      const response = await authService.forgotPassword(data);
      addToast({
        title: 'Token Generated',
        message: response.detail,
        type: 'success',
      });
      if (response.token) {
        setResetToken(response.token);
      }
    } catch (err: any) {
      const errMsg = err.response?.data?.detail || 'Failed to request password reset.';
      addToast({
        title: 'Error',
        message: errMsg,
        type: 'error',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-md space-y-8 rounded-xl border border-border bg-card p-8 shadow-lg">
        <div className="text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Key className="h-6 w-6" />
          </div>
          <h2 className="mt-6 text-3xl font-extrabold tracking-tight">Forgot Password</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Enter your registered email to receive a password reset token.
          </p>
        </div>

        {!resetToken ? (
          <form className="mt-8 space-y-6" onSubmit={handleSubmit(onSubmit)}>
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-muted-foreground mb-1">
                Email Address
              </label>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-muted-foreground">
                  <Mail className="h-5 w-5" />
                </div>
                <input
                  id="email"
                  type="email"
                  disabled={isSubmitting}
                  className={`block w-full rounded-md border bg-background py-2.5 pl-10 pr-3 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-1 sm:text-sm ${
                    errors.email ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : 'border-input focus:border-primary focus:ring-primary'
                  }`}
                  placeholder="name@company.com"
                  {...register('email')}
                />
              </div>
              {errors.email && <p className="mt-1 text-xs text-red-500">{errors.email.message}</p>}
            </div>

            <div className="flex flex-col gap-3">
              <button
                type="submit"
                disabled={isSubmitting}
                className="flex w-full justify-center rounded-md bg-primary py-2.5 px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/95 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Requesting...
                  </>
                ) : (
                  'Generate Reset Token'
                )}
              </button>

              <Link
                to="/login"
                className="flex items-center justify-center text-sm font-medium text-muted-foreground hover:text-foreground"
              >
                <ArrowLeft className="mr-2 h-4 w-4" /> Back to Sign In
              </Link>
            </div>
          </form>
        ) : (
          <div className="mt-8 space-y-6">
            <div className="rounded-md bg-amber-50 dark:bg-amber-950/20 p-4 border border-amber-500/20">
              <h3 className="text-sm font-semibold text-amber-800 dark:text-amber-300">Testing Token Generated:</h3>
              <p className="mt-2 font-mono text-xs break-all bg-background border rounded p-2 text-foreground select-all">
                {resetToken}
              </p>
              <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
                Copy the token above and use it to reset your password.
              </p>
            </div>

            <div className="flex flex-col gap-3">
              <button
                onClick={() => navigate('/reset-password', { state: { token: resetToken } })}
                className="flex w-full justify-center rounded-md bg-primary py-2.5 px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/95 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
              >
                Proceed to Reset Password
              </button>

              <button
                onClick={() => setResetToken(null)}
                className="flex w-full justify-center rounded-md border border-input bg-background py-2.5 px-4 text-sm font-semibold hover:bg-accent focus:outline-none"
              >
                Request Again
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
