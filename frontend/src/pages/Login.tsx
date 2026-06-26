import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService } from '../services/auth';
import { Sparkles, Mail, Lock, ArrowRight, Loader2, User } from 'lucide-react';

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const data = await authService.login(email, password);
      localStorage.setItem('token', data.access_token);
      navigate('/');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'An error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen relative flex items-center justify-center p-4 overflow-hidden bg-[#FBFBFA]">
      {/* Soft warm ambient background glows */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/3 w-[500px] h-[500px] bg-orange-200/10 rounded-full blur-[140px]" />
        <div className="absolute bottom-1/4 right-1/3 w-[500px] h-[500px] bg-amber-100/20 rounded-full blur-[140px]" />
      </div>

      <div className="relative w-full max-w-[400px]">
        {/* Transparent card wrapper on mobile, shadowed card on desktop */}
        <div className="relative bg-transparent sm:bg-white sm:border sm:border-slate-100 rounded-3xl p-4 sm:p-10 sm:shadow-[0_20px_50px_rgba(249,115,22,0.05)]">
          
          {/* Logo, Avatar + title */}
          <div className="text-center mb-8">
            <div className="mx-auto w-20 h-20 rounded-full bg-orange-50 border border-orange-100 flex items-center justify-center mb-6">
              <User className="w-10 h-10 text-orange-600" />
            </div>

            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-50 border border-slate-100 mb-4">
              <Sparkles className="w-3 h-3 text-orange-600" />
              <span className="text-[10px] uppercase tracking-[0.15em] text-slate-600 font-semibold">
                AI Reel Studio
              </span>
            </div>

            <h2 className="text-2xl font-bold tracking-tight text-slate-900">
              Welcome back
            </h2>
            <p className="mt-1.5 text-xs text-slate-500">
              Sign in to continue creating with AI
            </p>
          </div>

          {/* Form */}
          <form className="space-y-5" onSubmit={handleSubmit}>
            {error && (
              <div className="p-3 bg-red-50 border border-red-100 rounded-2xl text-red-600 text-xs text-center font-medium">
                {error}
              </div>
            )}

            <div className="space-y-4">
              {/* Email */}
              <div className="relative flex items-center border-b border-slate-200 focus-within:border-orange-500 py-2.5 transition-all duration-200">
                <div className="text-slate-400">
                  <Mail className="h-4 w-4" />
                </div>
                <input
                  id="email-address"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  className="w-full bg-transparent pl-3 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                  placeholder="Email ID"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>

              {/* Password */}
              <div className="relative flex items-center border-b border-slate-200 focus-within:border-orange-500 py-2.5 transition-all duration-200">
                <div className="text-slate-400">
                  <Lock className="h-4 w-4" />
                </div>
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  className="w-full bg-transparent pl-3 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
                  placeholder="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 rounded-full py-3.5 text-sm font-bold tracking-wider uppercase text-white bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 active:from-orange-700 active:to-orange-800 shadow-sm shadow-orange-600/10 transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed mt-4"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Signing in...
                </>
              ) : (
                <>
                  Sign In
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>

            {/* Divider */}
            <div className="flex items-center gap-3 py-2">
              <div className="flex-1 h-px bg-slate-100" />
              <span className="text-[9px] uppercase tracking-[0.15em] text-slate-400">or</span>
              <div className="flex-1 h-px bg-slate-100" />
            </div>

            {/* Signup Link */}
            <button
              type="button"
              className="w-full text-xs text-slate-500 hover:text-slate-800 transition-colors py-1"
              onClick={() => navigate('/signup')}
            >
              Don't have an account?{' '}
              <span className="text-orange-600 hover:text-orange-500 font-semibold ml-0.5">
                Create one
              </span>
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
