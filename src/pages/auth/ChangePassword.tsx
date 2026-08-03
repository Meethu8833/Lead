import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { useNavigate } from 'react-router-dom';
import { useNotificationStore } from '../../app/store';
import { authService } from '../../services/auth';
import { Loader2, Key, Eye, EyeOff } from 'lucide-react';

const passwordRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-=_+[\]{}|;:',.<>?/`~]).{8,}$/;

const changePasswordSchema = z
  .object({
    oldPassword: z.string().min(1, 'Current password is required'),
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

type ChangePasswordFormValues = z.infer<typeof changePasswordSchema>;

export default function ChangePassword() {
  const navigate = useNavigate();
  const { addToast } = useNotificationStore();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showOldPassword, setShowOldPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
    reset,
  } = useForm<ChangePasswordFormValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: {
      oldPassword: '',
      newPassword: '',
      confirmPassword: '',
    },
  });

  const onSubmit = async (data: ChangePasswordFormValues) => {
    setIsSubmitting(true);
    try {
      await authService.changePassword({
        old_password: data.oldPassword,
        new_password: data.newPassword,
      });

      addToast({
        title: 'Password Changed',
        message: 'Your password has been successfully updated. Other active sessions have been invalidated.',
        type: 'success',
      });

      reset();
      navigate('/');
    } catch (err: any) {
      const errMsg = err.response?.data?.detail || 'Failed to update password. Please check your current password.';
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
    <div className="max-w-md mx-auto p-6 bg-card border border-border rounded-xl shadow-lg mt-8">
      <div className="flex items-center gap-3 mb-6">
        <div className="h-10 w-10 flex items-center justify-center rounded-full bg-primary/10 text-primary">
          <Key className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-xl font-bold tracking-tight">Change Password</h2>
          <p className="text-sm text-muted-foreground">Update your account login password.</p>
        </div>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div>
          <label htmlFor="oldPassword" className="block text-sm font-medium text-muted-foreground mb-1">
            Current Password
          </label>
          <div className="relative">
            <input
              id="oldPassword"
              type={showOldPassword ? 'text' : 'password'}
              disabled={isSubmitting}
              className={`block w-full rounded-md border bg-background py-2 px-3 pr-10 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-1 sm:text-sm ${
                errors.oldPassword ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : 'border-input focus:border-primary focus:ring-primary'
              }`}
              placeholder="••••••••"
              {...register('oldPassword')}
            />
            <button
              type="button"
              onClick={() => setShowOldPassword(!showOldPassword)}
              className="absolute inset-y-0 right-0 flex items-center pr-3 text-muted-foreground hover:text-foreground"
            >
              {showOldPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {errors.oldPassword && <p className="mt-1 text-xs text-red-500">{errors.oldPassword.message}</p>}
        </div>

        <div>
          <label htmlFor="newPassword" className="block text-sm font-medium text-muted-foreground mb-1">
            New Password
          </label>
          <div className="relative">
            <input
              id="newPassword"
              type={showNewPassword ? 'text' : 'password'}
              disabled={isSubmitting}
              className={`block w-full rounded-md border bg-background py-2 px-3 pr-10 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-1 sm:text-sm ${
                errors.newPassword ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : 'border-input focus:border-primary focus:ring-primary'
              }`}
              placeholder="••••••••"
              {...register('newPassword')}
            />
            <button
              type="button"
              onClick={() => setShowNewPassword(!showNewPassword)}
              className="absolute inset-y-0 right-0 flex items-center pr-3 text-muted-foreground hover:text-foreground"
            >
              {showNewPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
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
              className={`block w-full rounded-md border bg-background py-2 px-3 pr-10 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-1 sm:text-sm ${
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
              {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {errors.confirmPassword && (
            <p className="mt-1 text-xs text-red-500">{errors.confirmPassword.message}</p>
          )}
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="flex w-full justify-center rounded-md bg-primary py-2 px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/95 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Updating Password...
            </>
          ) : (
            'Change Password'
          )}
        </button>
      </form>
    </div>
  );
}
