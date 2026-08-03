import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import { useNotificationStore } from '../../app/store';
import { authService } from '../../services/auth';
import { Loader2, Lock, Eye, EyeOff } from 'lucide-react';

const passwordRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-=_+[\]{}|;:',.<>?/`~]).{8,}$/;

const resetSchema = z
  .object({
    token: z.string().trim().min(1, 'Token is required'),
    newPassword: z
      .string()
      .min(8, 'Password must be at least 8 characters')
      .regex(
        passwordRegex,
        'Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character'
      ),
    confirmPassword: z.string().min(1, 'Confirm password is required'),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  });

type ResetFormValues = z.infer<typeof resetSchema>;

export default function ResetPassword() {
  const location = useLocation();
  const navigate = useNavigate();
  const { addToast } = useNotificationStore();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // Pre-fill token if sent via state (e.g. from ForgotPassword test flow)
  const initialToken = (location.state as any)?.token || '';

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ResetFormValues>({
    resolver: zodResolver(resetSchema),
    defaultValues: {
      token: initialToken,
      newPassword: '',
      confirmPassword: '',
    },
  });

  const onSubmit = async (data: ResetFormValues) => {
    setIsSubmitting(true);
    try {
      await authService.resetPassword({
        token: data.token,
        new_password: data.newPassword,
      });

      addToast({
        title: 'Password Reset Success',
        message: 'Your password has been successfully reset. Please sign in with your new password.',
        type: 'success',
      });

      navigate('/login');
    } catch (err: any) {
      const errMsg = err.response?.data?.detail || 'Failed to reset password. The token may be expired or invalid.';
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
            <Lock className="h-6 w-6" />
          </div>
          <h2 className="mt-6 text-3xl font-extrabold tracking-tight">Reset Password</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Complete the form below to choose a new password.
          </p>
        </div>

        <form className="mt-8 space-y-6" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-4 rounded-md">
            <div>
              <label htmlFor="token" className="block text-sm font-medium text-muted-foreground mb-1">
                Reset Token
              </label>
              <input
                id="token"
                type="text"
                disabled={isSubmitting}
                className={`block w-full rounded-md border bg-background py-2.5 px-3 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-1 sm:text-sm ${
                  errors.token ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : 'border-input focus:border-primary focus:ring-primary'
                }`}
                placeholder="Paste your reset token here"
                {...register('token')}
              />
              {errors.token && <p className="mt-1 text-xs text-red-500">{errors.token.message}</p>}
            </div>

            <div>
              <label htmlFor="newPassword" className="block text-sm font-medium text-muted-foreground mb-1">
                New Password
              </label>
              <div className="relative">
                <input
                  id="newPassword"
                  type={showPassword ? 'text' : 'password'}
                  disabled={isSubmitting}
                  className={`block w-full rounded-md border bg-background py-2.5 px-3 pr-10 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-1 sm:text-sm ${
                    errors.newPassword ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : 'border-input focus:border-primary focus:ring-primary'
                  }`}
                  placeholder="••••••••"
                  {...register('newPassword')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                </button>
              </div>
              {errors.newPassword && <p className="mt-1 text-xs text-red-500">{errors.newPassword.message}</p>}
            </div>

            <div>
              <label htmlFor="confirmPassword" className="block text-sm font-medium text-muted-foreground mb-1">
                Confirm New Password
              </label>
              <div className="relative">
                <input
                  id="confirmPassword"
                  type={showConfirmPassword ? 'text' : 'password'}
                  disabled={isSubmitting}
                  className={`block w-full rounded-md border bg-background py-2.5 px-3 pr-10 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-1 sm:text-sm ${
                    errors.confirmPassword ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : 'border-input focus:border-primary focus:ring-primary'
                  }`}
                  placeholder="••••••••"
                  {...register('confirmPassword')}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-muted-foreground hover:text-foreground"
                >
                  {showConfirmPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                </button>
              </div>
              {errors.confirmPassword && (
                <p className="mt-1 text-xs text-red-500">{errors.confirmPassword.message}</p>
              )}
            </div>
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
                  Resetting Password...
                </>
              ) : (
                'Reset Password'
              )}
            </button>

            <Link
              to="/login"
              className="text-center text-sm font-medium text-muted-foreground hover:text-foreground"
            >
              Back to Sign In
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
