import { Route, Routes } from 'react-router-dom';

import { Layout } from '@/components/Chrome';
import Home from '@/routes/Home';
import Knowledge from '@/routes/Knowledge';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/knowledge" element={<Knowledge />} />
        {/* A marketing site has no 404 page to speak of, so anything unknown
            goes home rather than showing the router's default blank. */}
        <Route path="*" element={<Home />} />
      </Routes>
    </Layout>
  );
}
