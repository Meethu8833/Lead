import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuthStore, useNotificationStore } from '../../app/store';
import { authService } from '../../services/auth';
import { employeeService } from '../../services/employee';
import { Eye, EyeOff, Lock, Mail, Loader2 } from 'lucide-react';

const loginSchema = z.object({
  email: z.string().trim().min(1, 'Email is required').email('Invalid email address'),
  password: z.string().min(1, 'Password is required'),
  rememberMe: z.boolean().default(false),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login: setAuthStoreLogin } = useAuthStore();
  const { addToast } = useNotificationStore();
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: '',
      password: '',
      rememberMe: false,
    },
  });

  const from = (location.state as any)?.from?.pathname || '/';

  const onSubmit = async (data: LoginFormValues) => {
    setIsSubmitting(true);
    try {
      // 1. Authenticate with credentials
      const tokens = await authService.login({
        email: data.email,
        password: data.password,
      });

      // 2. Commit tokens to store and storage
      setAuthStoreLogin(tokens.access_token, tokens.refresh_token, data.rememberMe);

      // 3. Fetch profile and permissions
      const [profile, permissions] = await Promise.all([
        authService.me(),
        employeeService.getPermissions(),
      ]);

      // 4. Update store profile
      useAuthStore.getState().loadProfile(profile, permissions);

      addToast({
        title: 'Welcome Back',
        message: `Successfully logged in as ${profile.first_name} ${profile.last_name}`,
        type: 'success',
      });

      // 5. Navigate to destination
      navigate(from, { replace: true });
    } catch (err: any) {
      console.error(err);
      const errMsg = err.response?.data?.detail || 'Invalid email or password. Please try again.';
      addToast({
        title: 'Login Failed',
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
          <h2 className="mt-6 text-3xl font-extrabold tracking-tight">Colour Lab ERP</h2>
          <p className="mt-2 text-sm text-muted-foreground">Sign in to your account</p>
        </div>

        <form className="mt-8 space-y-6" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-4 rounded-md">
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
                  autoComplete="email"
                  disabled={isSubmitting}
                  className={`block w-full rounded-md border bg-background py-2.5 pl-10 pr-3 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-1 sm:text-sm ${
                    errors.email ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : 'border-input focus:border-primary focus:ring-primary'
                  }`}
                  placeholder="name@company.com"
                  {...register('register' in errors ? 'email' : 'email')} // Using register wrapper directly
                />
              </div>
              {errors.email && <p className="mt-1 text-xs text-red-500">{errors.email.message}</p>}
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label htmlFor="password" className="block text-sm font-medium text-muted-foreground">
                  Password
                </label>
                <Link
                  to="/forgot-password"
                  className="text-xs font-semibold text-primary hover:text-primary/85"
                >
                  Forgot password?
                </Link>
              </div>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-muted-foreground">
                  <Lock className="h-5 w-5" />
                </div>
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  disabled={isSubmitting}
                  className={`block w-full rounded-md border bg-background py-2.5 pl-10 pr-10 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-1 sm:text-sm ${
                    errors.password ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : 'border-input focus:border-primary focus:ring-primary'
                  }`}
                  placeholder="••••••••"
                  {...register('password')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                </button>
              </div>
              {errors.password && <p className="mt-1 text-xs text-red-500">{errors.password.message}</p>}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center">
              <input
                id="rememberMe"
                type="checkbox"
                disabled={isSubmitting}
                className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                {...register('rememberMe')}
              />
              <label htmlFor="rememberMe" className="ml-2 block text-sm text-foreground">
                Remember login
              </label>
            </div>
          </div>

          <div>
            <button
              type="submit"
              disabled={isSubmitting}
              className="group relative flex w-full justify-center rounded-md bg-primary py-2.5 px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/95 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Signing in...
                </>
              ) : (
                'Sign In'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
