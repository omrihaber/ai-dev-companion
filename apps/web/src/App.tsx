import { Link, Route, Routes, useParams } from "react-router-dom";
import { Workspace } from "./components/Workspace";
import { HistoryPage } from "./pages/HistoryPage";
import { SettingsPage } from "./pages/SettingsPage";

function ReviewView() {
  const { id } = useParams();
  return <Workspace loadId={id} />;
}

export default function App() {
  return (
    <div className="app">
      <nav className="topnav">
        <span className="logo">⬡ AI Dev Companion</span>
        <Link to="/">New Review</Link>
        <Link to="/history">History</Link>
        <Link to="/settings">Settings</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Workspace />} />
        <Route path="/review/:id" element={<ReviewView />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </div>
  );
}
