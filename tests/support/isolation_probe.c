/* Unpaid, networkless namespace probe. Never a vendor/model-success fixture. */
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef HOST_SENTINEL
#error HOST_SENTINEL must name the test-owned inaccessible host file
#endif
#ifndef HOST_PORT
#error HOST_PORT must name the test-owned loopback listener
#endif

int main(void) {
    int hidden = open(HOST_SENTINEL, O_RDONLY);
    int host_hidden = hidden < 0;
    if (hidden >= 0) close(hidden);
    int readonly = open("/workspace/readonly.txt", O_WRONLY);
    int write_denied = readonly < 0 && errno == EROFS;
    if (readonly >= 0) close(readonly);
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in peer = { .sin_family = AF_INET,
        .sin_port = htons(HOST_PORT), .sin_addr.s_addr = htonl(INADDR_LOOPBACK) };
    int network_denied = sock >= 0 && connect(sock, (struct sockaddr *)&peer, sizeof(peer)) < 0;
    if (sock >= 0) close(sock);
    int env_hidden = getenv("IAI_PROBE_HOST_MARKER") == NULL && getenv("PATH") == NULL;
    int config_hidden = access("/home/.mcp.json", F_OK) < 0;
    pid_t descendant = fork();
    if (descendant < 0) return 4;
    if (descendant == 0) {
        if (setsid() < 0) _exit(5);
        unsigned int counter = 0;
        for (;;) {
            int heartbeat = open("/workspace/heartbeat", O_WRONLY | O_TRUNC);
            if (heartbeat < 0) _exit(6);
            char value[32];
            int length = snprintf(value, sizeof(value), "%u", ++counter);
            if (write(heartbeat, value, length) != length) _exit(7);
            close(heartbeat);
            usleep(20000);
        }
    }
    printf("{\"host_hidden\":%s,\"write_denied\":%s,\"network_denied\":%s,"
           "\"environment_hidden\":%s,\"config_hidden\":%s,\"setsid_started\":true}\n",
        host_hidden ? "true" : "false", write_denied ? "true" : "false",
        network_denied ? "true" : "false", env_hidden ? "true" : "false",
        config_hidden ? "true" : "false");
    fflush(stdout);
    for (;;) pause();
}
