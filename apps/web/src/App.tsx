import { Link, Route, Routes, useParams } from "react-router-dom";
import { NewReview } from "./components/NewReview";
import { Workspace } from "./components/Workspace";
import { HistoryPage } from "./pages/HistoryPage";

function ReviewView() {
  const { id } = useParams();
  return <Workspace loadId={id} />;
}

export default function App() {
  return (
    <div className="app">
      <nav className="topnav">
        <span className="logo">⬡ AI Dev Companion</span>
        <Link to="/">Review</Link>
        <Link to="/history">History</Link>
      </nav>
      <Routes>
        <Route path="/" element={<NewReview />} />
        <Route path="/review/:id" element={<ReviewView />} />
        <Route path="/history" element={<HistoryPage />} />
      </Routes>
    </div>
  );
}
