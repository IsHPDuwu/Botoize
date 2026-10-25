import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';
afterEach(cleanup);
configure({ asyncUtilTimeout: 5000 });
Object.defineProperty(window, 'matchMedia', { value: () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }) });
// jsdom has no layout engine; Fluent MessageBar observes its container size.
Object.defineProperty(window, 'ResizeObserver', { configurable: true, writable: true, value: class {
	observe() {}
	unobserve() {}
	disconnect() {}
} });