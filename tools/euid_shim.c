/* Shim LD_PRELOAD : fait croire à makepkg qu'il tourne en uid 1000 (non-root). */
int geteuid(void) { return 1000; }
int getuid(void) { return 1000; }
int getegid(void) { return 1000; }
int getgid(void) { return 1000; }
