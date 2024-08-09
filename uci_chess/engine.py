from pathlib import Path
import re
import logging
from .core import EngineCore


class UCIEngine:
    RE_PARSE_INFO = re.compile(r"info (.*)score ((?:cp|mate) -?\d+)(.*)\s+pv\s+(.*)")
    RE_BEST_MOVE = re.compile(
        r"bestmove\s*([abcdefgh12345678]{4})(?:\s*ponder\s*([abcdefgh12345678]{4}))?"
    )
    output_buffer = []

    def __init__(
        self,
        engine_binary_path: str | Path,
        options_override: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> None:
        self.timeout = timeout
        self.engine_binary_path = Path(engine_binary_path)
        if not self.engine_binary_path.exists():
            raise FileNotFoundError(
                f"Engine binary not found at {self.engine_binary_path}"
            )

        self.engine = EngineCore(engine_binary_path, timeout=timeout)
        self.default_option_override = options_override
        self.current_multi_pv = 1
        if options_override:
            for option_name, option_value in options_override.items():
                self.set_option(option_name, option_value)

    def _ucinewgame(self) -> None:
        self.engine.put("ucinewgame")
        self.engine.is_ready()

    def set_position(
        self, fen: str | None = None, moves: list[str] | None = None
    ) -> None:
        self._ucinewgame()

        if fen is None:
            position_str = "startpos"
        else:
            position_str = f"fen {fen}"

        if moves is None:
            moves_str = ""
        else:
            moves_str = f"moves {' '.join(moves)}"
        command_str = f"position {position_str} {moves_str}"
        logging.debug(command_str)
        self.engine.put(command_str)

    def set_option(self, name: str, option: str | None = None) -> None:
        if name not in self.engine.available_options:
            logging.warning(f'Engine does not support option "{name}"')
        else:
            value_str = f"value {option}" if option else ""
            command_str = f"setoption name {name} {value_str}"
            logging.debug(command_str)
            self.engine.put(command_str)

    def set_multi_pv(self, value=1):
        self.set_option("MultiPV", f"{value}")
        self.current_multi_pv = value

    def go(
        self,
        depth: int | None = None,
        wtime: int | None = None,
        btime: int | None = None,
        winc: int | None = None,
        binc: int | None = None,
        movetime: int | None = None,
        searchmoves: list[str] | None = None,
        nodes: int | None = None,
        raw_output: bool = False,
        **kwargs,
    ):
        if depth is None:
            depth_str = "infinite"
        else:
            depth_str = f"depth {depth}"

        if wtime is not None:
            wtime_str = f"wtime {wtime}"
        else:
            wtime_str = ""

        if btime is not None:
            btime_str = f"btime {btime}"
        else:
            btime_str = ""

        if winc is not None:
            winc_str = f"winc {winc}"
        else:
            winc_str = ""

        if binc is not None:
            binc_str = f"binc {binc}"
        else:
            binc_str = ""

        if movetime is not None:
            movetime_str = f"movetime {movetime}"
        else:
            movetime_str = ""

        if searchmoves is not None:
            searchmoves_str = f"searchmoves {' '.join(searchmoves)}"
        else:
            searchmoves_str = ""

        if nodes is not None:
            nodes_str = f"nodes {nodes}"
        else:
            nodes_str = ""

        param_list = [
            depth_str,
            wtime_str,
            btime_str,
            winc_str,
            binc_str,
            movetime_str,
            searchmoves_str,
            nodes_str,
        ]
        for param_name, param_val in kwargs.items():
            param_list.append(f"{param_name} {param_val}")
        command_str = f"go {' '.join([p for p in param_list if p])}"
        logging.debug(command_str)
        self.engine.put(command_str)

        if raw_output:
            resp = ""
            while "bestmove" not in resp:
                resp = self.engine.get()
                yield resp
        else:
            continue_flg = True
            next_resp = None
            while continue_flg:
                lines_list = []
                for i in range(self.current_multi_pv):
                    resp = self.engine.get()
                    print(f"resp == prev next_resp: {resp == next_resp}")
                    tmp_parsed_info = self.parse_info(resp)
                    while not tmp_parsed_info:
                        resp = self.engine.get()
                        tmp_parsed_info = self.parse_info(resp)
                    lines_list.append(tmp_parsed_info)
                output = {
                    "next_move": lines_list[0]["next_move"],
                    "score": lines_list[0]["score"],
                    "lines": lines_list,
                    "bestmove": None,
                    "ponder": None,
                }
                next_resp = self.engine.view(index_to_view=0)
                if "bestmove" in next_resp:
                    resp = self.engine.get()
                    match = self.RE_BEST_MOVE.match(resp)
                    output["bestmove"] = match.group(1)
                    output["ponder"] = match.group(2)
                    continue_flg = False
                yield output

    def parse_info(self, text: str):
        match = self.RE_PARSE_INFO.match(text)
        if not match:
            return None
        score_tmp = match.group(2).split(" ")
        pv_tmp = match.group(4).split(" ")
        other_tmp = (match.group(1).strip() + " " + match.group(3).strip()).split(" ")
        tmp_output = {
            "score": {"mate": None, "cp": None},
            "moves": pv_tmp,
            "next_move": pv_tmp[0],
        }
        tmp_output["score"][score_tmp[0]] = int(score_tmp[1])
        for i in range(0, len(other_tmp), 2):
            tmp_output[other_tmp[i]] = other_tmp[i + 1]
        for key in ["depth", "seldepth", "multipv", "time"]:
            tmp_output[key] = int(tmp_output[key])
        return tmp_output
