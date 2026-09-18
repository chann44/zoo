import {
  BrowserRouter,
  Routes,
  Route,
} from "react-router-dom";
import SandboxManager from "./sandbox-manager";
import Desktop from "./desktop";


export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={<SandboxManager />}
        />

        <Route
          path="/sandboxes/:id"
          element={<Desktop />}
        />
      </Routes>
    </BrowserRouter>
  );
}