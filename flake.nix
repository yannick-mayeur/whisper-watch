{
  description = "Whisper Watch - A service for automated audio/video transcription";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem
      (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};

          python = pkgs.python311;
          pythonPackages = python.pkgs;

          whisper-watch = pythonPackages.buildPythonApplication {
            pname = "whisper-watch";
            version = "0.1.0";

            src = ./.; # Assumes whisper-watch.py is in the same directory

            format = "other";

            propagatedBuildInputs = with pythonPackages; [
              openai-whisper
              watchdog
              ffmpeg-python
            ];

            nativeBuildInputs = [
              pkgs.makeWrapper
            ];

            dontBuild = true;

            installPhase = ''
              mkdir -p $out/bin
              cp whisper-watch.py $out/bin/whisper-watch
              chmod +x $out/bin/whisper-watch
              wrapProgram $out/bin/whisper-watch \
                --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.ffmpeg ]}
            '';

            # Skip phases we don't need
            dontConfigure = true;
            doCheck = false;
            pythonImportsCheck = [ ];
          };
        in
        {
          packages.default = whisper-watch;

          packages.whisper-watch = whisper-watch;
        }
      ) // {
      nixosModules.default = { config, lib, pkgs, ... }:
        with lib;
        let
          cfg = config.services.whisper-watch;
        in
        {
          options.services.whisper-watch = {
            enable = mkEnableOption "whisper watch service";

            package = mkOption {
              type = types.package;
              default = self.packages.${pkgs.system}.whisper-watch;
              description = "The whisper-watch package to use";
            };

            watchDir = mkOption {
              type = types.str;
              description = "Directory to watch for new media files";
            };

            pendingDir = mkOption {
              type = types.str;
              description = "Directory for files being processed";
            };

            outputDir = mkOption {
              type = types.str;
              description = "Directory to store transcriptions";
            };

            modelSize = mkOption {
              type = types.enum [ "tiny" "base" "small" "medium" "large" "turbo" ];
              default = "base";
              description = "Whisper model size to use";
            };

            user = mkOption {
              type = types.str;
              default = "whisper-watch";
              description = "User to run the service as";
            };

            group = mkOption {
              type = types.str;
              default = "whisper-watch";
              description = "Group to run the service as";
            };

            cacheDir = mkOption {
              type = types.str;
              description = "Directory to store Whisper model cache";
              default = "/var/lib/whisper-watch/cache";
            };
          };

          config = mkIf cfg.enable {
            # Create user and group if they don't exist
            users.users.${cfg.user} = {
              isSystemUser = true;
              group = cfg.group;
              description = "Whisper Watch service user";
            };

            users.groups.${cfg.group} = { };

            systemd.tmpfiles.rules = [
              "d '${cfg.cacheDir}' 0750 ${cfg.user} ${cfg.group} - -"
            ];

            # Create the service
            systemd.services.whisper-watch = {
              description = "Whisper Watch Service";
              after = [ "network.target" ];
              wantedBy = [ "multi-user.target" ];

              environment = {
                WHISPER_WATCH_DIR = cfg.watchDir;
                WHISPER_PENDING_DIR = cfg.pendingDir;
                WHISPER_OUTPUT_DIR = cfg.outputDir;
                WHISPER_MODEL_SIZE = cfg.modelSize;
                XDG_CACHE_HOME = cfg.cacheDir;
              };

              serviceConfig = {
                ExecStart = "${cfg.package}/bin/whisper-watch";
                Restart = "always";
                RestartSec = "10s";

                User = cfg.user;
                Group = cfg.group;

                PrivateTmp = true;
              };
            };
          };
        };
    };
}
