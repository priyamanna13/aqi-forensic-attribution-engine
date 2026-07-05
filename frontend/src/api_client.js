/**
 * AeroTrace AI — Centralized API Handshake Client
 * Phase 1: Live Ngrok Tunnel Integration
 */
export const API = {
    // Anish ka live tunnel endpoint
    BASE_URL: "http://localhost:5000", 

    async getStations() {
        const response = await fetch(`${this.BASE_URL}/api/v1/stations`, {
            headers: {
                'ngrok-skip-browser-warning': 'true',
                'Accept': 'application/json'
            }
        });
        return await response.json();
    },

    async getSources() {
        const response = await fetch(`${this.BASE_URL}/api/v1/sources`, {
            headers: {
                'ngrok-skip-browser-warning': 'true',
                'Accept': 'application/json'
            }
        });
        return await response.json();
    },

    async getWindCone(stationName, timestamp = null) {
        let url = `${this.BASE_URL}/api/v1/cone/${stationName}`;
        if (timestamp) url += `?timestamp=${timestamp}`;
        const response = await fetch(url, {
            headers: {
                'ngrok-skip-browser-warning': 'true',
                'Accept': 'application/json'
            }
        });
        return await response.json();
    },

    async getAttribution(stationName) {
        const response = await fetch(`${this.BASE_URL}/api/v1/attribution/${stationName}`, {
            headers: {
                'ngrok-skip-browser-warning': 'true',
                'Accept': 'application/json'
            }
        });
        return await response.json();
    },

    async getTimeline(stationName) {
        const response = await fetch(`${this.BASE_URL}/api/v1/timeline/${stationName}`, {
            headers: {
                'ngrok-skip-browser-warning': 'true',
                'Accept': 'application/json'
            }
        });
        return await response.json();
    },

    async getReplay(stationName, timestamp) {
        const response = await fetch(`${this.BASE_URL}/api/v1/replay/${stationName}?timestamp=${encodeURIComponent(timestamp)}`, {
            headers: {
                'ngrok-skip-browser-warning': 'true',
                'Accept': 'application/json'
            }
        });
        return await response.json();
    }
};
