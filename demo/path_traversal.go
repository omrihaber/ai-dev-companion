package main

import (
	"net/http"
	"os"
)

func handler(w http.ResponseWriter, r *http.Request) {
	name := r.URL.Query().Get("file")
	// VULN: user input joined into a filesystem path -> path traversal (../../etc/passwd)
	// BUG: the read error is ignored, so failures are silently served as empty bodies
	data, _ := os.ReadFile("/var/data/" + name)
	w.Write(data)
}

func main() {
	http.HandleFunc("/download", handler)
	http.ListenAndServe(":8080", nil)
}
