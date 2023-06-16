from typing import Any
import discord
from discord.ext import tasks,commands
from discord import app_commands
import logging
from discord.interactions import Interaction
from dotenv import load_dotenv
import os
import math
from enum import Enum
import numpy as np
import logging
import asyncio

logging.basicConfig(level=logging.INFO)

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_GUILD = os.getenv("DISCORD_GUILD")
DISCORD_GUILD_ID = discord.Object(id=os.getenv("DISCORD_GUILD_ID"))
VALID_CHANNEL_ID = os.getenv("VALID_CHANNEL_ID")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True

#inherited commands.Bot class to include setup_hook to sync bot's commands to the server
class BotClass(commands.Bot):
    def __init__(self,*,command_prefix,intents: discord.Intents):
        super().__init__(command_prefix=commands.when_mentioned_or(command_prefix),intents=intents)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=DISCORD_GUILD_ID)
        await self.tree.sync(guild=DISCORD_GUILD_ID)

#discord client created using commands extension
client = BotClass(command_prefix = "h!", intents = intents)

@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')
    
    guild = discord.utils.get(client.guilds, name = DISCORD_GUILD)
    
    print(f"{client.user} is connected to: \n", f"{guild.name}(id: {guild.id})")
    
    print("\n \n \n -------------")

#------------------------------

class FinFacFoeGame():
    #CONSTANTS
    X = -1 #Challenger
    O = 1 #Boardmaster
    TIE = 2
    CONTINUE = 0
    STATES = Enum("TRAP STATES",["FREE","FIXED","COL","ROW"])
    CHECK = Enum("LINE CHECK",["ANY","COL","ROW"])

    def __init__(self,player_challenger: discord.Member,player_boardmaster: discord.Member):
        #Public references
        self.public_view = None
        self.public_msg = None

        #Private references
        self.private_view = None
        self.private_msg = None

        #win flag
        self.win_flag = False

        #User references
        self.boardmaster = player_boardmaster
        self.challenger = player_challenger

        #Board
        self.board = [
            [0, 0, 0],
            [0, 0, 0],
            [0, 0, 0],
        ]

        #Piece counter
        self.count = 0

        #Current player
        self.current_player = self.X

        #Col/Row locks
        self.c = None
        self.r = None

        #Record current input coords
        self.x = None
        self.y = None

        #Boardmaster current trap state
        self.bm_state = self.STATES.FREE
    
    def get_current_turn(self):
        return math.floor(self.count*0.5)+1

    def get_boardmaster_text(self):
        return f"[O] {self.boardmaster.mention}\n"
    
    def get_challenger_text(self):
        return f"[X] {self.challenger.mention}\n"
    
    def save_input(self,x,y):
        self.x = x
        self.y = y
    
    def transfer_turn_to(self,piece):
        self.count +=1
        self.current_player = piece

    def check_rule(self):
        #Assume position is unoccupied

        #Challenger turn
        if self.current_player == self.X:
            #first turn for Challenger
            if self.count == 0:
                logging.info("First X turn")    
                if self.x == 1 and self.y == 1:
                    #Invalid move
                    logging.info("First X move must not be in center")
                    return False
                else:
                    #No restriction in other places
                    logging.info("Valid X move")
                    return True
            #any other turn
            else:
                #All places are valid as long as not occupied
                logging.info("X moves are always valid after first turn if position is unoccupied")
                return True
        #Boardmaster turn
        else:
            if self.is_valid_bm_move():
                return True
            else:
                return False

    def is_valid_bm_move(self):
        #first turn for BM, second turn overall
        if self.count == 1:
            logging.info("First O turn")
            #Check if placed on middle
            if self.x == 1 and self.y == 1:
                #Invalid move
                logging.info("First O move must not be in center")
                return False 
            else:
                #lock bm
                self.c = self.x
                self.r = self.y
                self.bm_state = self.STATES.FIXED
                logging.info("Valid Free O move; state now FIXED")
                return True
        #Any other turn
        else:
            logging.info("Other O turn")
            match self.bm_state:
                #BM freely can place in the remaining spaces
                case self.STATES.FREE:
                    self.c = self.x
                    self.r = self.y
                    self.bm_state = self.STATES.FIXED
                    logging.info("Valid Free O move; state now FIXED")
                    return True

                #BM will be fixed to an axis
                case self.STATES.FIXED:
                    if self.is_moves_available(self.CHECK.ANY):
                        #BM gets fixed to an axis
                        if self.c == self.x:
                            self.bm_state = self.STATES.COL
                            logging.info("Valid Fixed O move; state now COL")
                            return True
                        elif self.r == self.y:
                            self.bm_state = self.STATES.ROW
                            logging.info("Valid Fixed O move; state now ROW")
                            return True
                        #Violated rule
                        else:
                            logging.info("Invalid Fixed O move")
                            return False
                    #No available move, make BM free
                    else:
                        self.bm_state = self.STATES.FREE
                        logging.info("Valid Released O move; state now FREE")
                        return True

                case self.STATES.COL:
                    if self.is_moves_available(self.CHECK.COL):
                        #If position escaped the saved column
                        if self.x != self.c:
                            logging.info("Invalid COL O move")
                            return False
                        else:
                            logging.info("Valid COL O move; state remains COL")
                            return True
                    #No available move, make BM free
                    else:
                        logging.info("Valid Released O move; state now FREE")
                        self.bm_state = self.STATES.FREE
                        return True
                
                case self.STATES.ROW:
                    if self.is_moves_available(self.CHECK.ROW):
                        #If position escaped the saved row
                        if self.y != self.r:
                            logging.info("Invalid ROW O move")
                            return False
                        else:
                            logging.info("Valid ROW O move; state remains ROW")
                            return True
                    #No available move, make BM free
                    else:
                        self.bm_state = self.STATES.FREE
                        logging.info("Valid Released O move; state now FREE")
                        return True

        return False

    def is_moves_available(self,check_axis):

        board_array = np.array(self.board)

        match check_axis:
            case self.CHECK.ANY:
                if 0 in board_array:
                    return True
                else:
                    return False
            case self.CHECK.COL:
                if 0 in board_array[:,self.c]:
                    return True
                else:
                    return False
            case self.CHECK.ROW:
                if 0 in board_array[self.r,:]:
                    return True
                else:
                    return False

    def is_won(self):
        board_array = np.array(self.board)
        #check horizontals
        if 3 in np.sum(board_array,1):
            return self.O
        elif -3 in np.sum(board_array,1):
            return self.X
        #check verticals
        if 3 in np.sum(board_array,0):
            return self.O
        elif -3 in np.sum(board_array,0):
            return self.X
        #check \ diagonal
        if np.trace(board_array) == 3:
            return self.O
        elif np.trace(board_array) == -3:
            return self.X
        #check / diagonal
        if np.trace(np.rot90(board_array)) == 3:
            return self.O
        elif np.trace(np.rot90(board_array)) == -3:
            return self.X
        #check tie
        if not 0 in board_array:
            return self.TIE
        
        #game continues
        return self.CONTINUE

    def update_board(self):
        self.board[self.y][self.x] = self.current_player

    def button_to_index(self,x,y):
        return x*3+y

    def disable_view(self):
        logging.info("Disabling public buttons")
        for button in self.public_view.children:
            button.disabled = True

        logging.info("Disabling private buttons")
        for button in self.private_view.children:
            button.disabled = True

        logging.info("All views stopped")
        self.public_view.stop()
        self.private_view.stop()

    def debug_board(self):
        output_board = self.board
        def replacer(elm):
            if elm == self.X:
                return "X"
            elif elm == self.O:
                return "O"
            else:
                return " "
        output_board = [[replacer(elm) for elm in row] for row in output_board]

        output = f"{output_board[0]}\n{output_board[1]}\n{output_board[2]}"
        return output

    async def on_update(self,input,interaction:discord.Interaction):

        logging.info(f"\nCurrent Player: {self.current_player}\nCurrent Count: {self.count}\nCurrent Board:\n{self.board}\nCurrent Inputted Button Coords: {input.x},{input.y}\nCurrent BM State: {self.bm_state}\nCurrent C R: {self.c},{self.r}\nCurrent View Used {'PUBLIC' if input.view.is_visible else 'PRIVATE'}\n\n")

        """
        if no winner (assume no winner if still clickable and receives callback)
            validate input
            if valid
                save input
                check in rules
                if valid
                    update board
                else
                    reject input
                display?
            
            check winner
            if winner found
                update?

        """

        #-Valid button press-

        #PUBLIC
        if input.view.is_visible:
            #Check if button is clickable
            button_state = self.board[input.y][input.x]
            #Check if position is occupied
            if button_state in (self.X,self.O):
                content = f"{self.get_challenger_text()}> Occupied spot"
                self.public_view.children[self.button_to_index(input.x,input.y)].style = discord.ButtonStyle.gray
                await interaction.response.edit_message(content=content, view=self.public_view)
                return

            #PUBLIC should only be for X
            if self.current_player != self.X:
                logging.info("silently ignore invalid turn")
                content = f"{self.get_challenger_text()}> Not your turn"
                await interaction.response.edit_message(content=content)
                return
            #PUBLIC should only be to challenger member
            if not self.challenger == interaction.user:
                logging.info("silently ignore invalid player")
                await interaction.response.send_message(f"This is not your board {interaction.user.mention}", ephemeral=True,delete_after=3)
                return

            #Save input
            self.save_input(input.x,input.y)

            #Check rules
            logging.info("Checking rules")
            if self.check_rule():
                logging.info("Rule passed")
                self.update_board()
                logging.info("Board updated")
                self.transfer_turn_to(self.O)
                logging.info(f"Transfering turn to {self.O}")

                index = self.button_to_index(self.x,self.y)

                #Update Public View
                self.public_view.children[index].style = discord.ButtonStyle.danger
                self.public_view.children[index].label = "X"
                self.public_view.children[index].disabled = True
                await interaction.response.edit_message(content=f"{self.get_challenger_text()}> It is [O]'s Turn",view=self.public_view)

                #Update Private View
                self.private_view.children[index].style = discord.ButtonStyle.danger
                self.private_view.children[index].label = "X"
                self.private_view.children[index].disabled = True
                await self.private_msg.edit(content = f"{self.get_boardmaster_text()}> It is [O] your turn", view=self.private_view)

                logging.info("UI updated")

            else:
                logging.info("Rule failed")
                #only rule broken is no piece in middle at first turn
                content = f"{self.get_challenger_text()}> Center position is prohibited on first turn. Try again."
                await interaction.response.edit_message(content=content)
                return

        #PRIVATE
        else:
            #Occupied button already disabled

            #PRIVATE should only be for O
            if self.current_player != self.O:
                logging.info("silently ignore invalid turn")
                content = f"{self.get_challenger_text()}> Not your turn"
                await interaction.response.edit_message(content=content)
                return
            #PRIVATE is only visible to boardmaster

            #Save input
            self.save_input(input.x,input.y)

            #Check rules
            logging.info("Checking rules")
            if self.check_rule():
                logging.info("Rule passed")
                self.update_board()
                logging.info("Board updated")
                self.transfer_turn_to(self.X)
                logging.info(f"Transfering turn to {self.X}")

                index = self.button_to_index(self.x,self.y)

                #Update Public View
                await self.public_msg.edit(content=f"{self.get_challenger_text()}> It is [X] your Turn",view=self.public_view)

                #Update Private View
                self.private_view.children[index].style = discord.ButtonStyle.success
                self.private_view.children[index].label = "O"
                self.private_view.children[index].disabled = True
                await interaction.response.edit_message(content = f"{self.get_boardmaster_text()}> It is [X]'s turn", view=self.private_view)

                logging.info("UI updated")

            else:
                logging.info("Rule failed")
                match self.bm_state:
                    case self.STATES.COL:
                        locked = "COL LOCKED"
                    case self.STATES.ROW:
                        locked = "ROW LOCKED"
                    case self.STATES.FIXED:
                        locked = "AXIS LOCKED"
                    case self.STATES.FREE:
                        content = f"{self.get_boardmaster_text()}> Center position is prohibited on first turn. Try again."
                        await interaction.response.edit_message(content=content)
                        return
                content = f"{self.get_boardmaster_text()}> You are {locked}. Try again."
                await interaction.response.edit_message(content=content)
                return
        
        #check if winner
        logging.info("Checking Win condition")
        match self.is_won():
            case self.CONTINUE:
                logging.info("Continue game")
                pass
            case self.X:
                logging.info("X wins")
                self.disable_view()

                await asyncio.sleep(0.5)

                await self.public_msg.edit(content=f"{self.get_challenger_text()}> You win", view=self.private_view)
                await self.private_msg.edit(content=f"{self.get_boardmaster_text()}> [X] wins", view=self.private_view)
                
                pass
            case self.O:
                logging.info("O wins")
                self.disable_view()

                await asyncio.sleep(0.5)

                await self.public_msg.edit(content=f"{self.get_challenger_text()}> [O] wins", view=self.private_view)
                await self.private_msg.edit(content=f"{self.get_boardmaster_text()}> You win", view=self.private_view)

                pass
            case self.TIE:
                logging.info("TIE")
                self.disable_view()

                await asyncio.sleep(0.5)

                await self.public_msg.edit(content=f"{self.get_challenger_text()}> TIE", view=self.private_view)
                await self.private_msg.edit(content=f"{self.get_boardmaster_text()}> TIE", view=self.private_view)
        
        logging.info(f"\n{self.debug_board()}\n")

        logging.info("---end of update function---\n\n")

#------------------------        

#UI view
class FinFacFoeView(discord.ui.View):

    def __init__(self,gamestate,is_visible):
        super().__init__()
        self.is_visible = is_visible
        self.gamestate: FinFacFoeGame = gamestate

        #populate the view with buttons
        for x in range(3):
            for y in range(3):
                self.add_item(FinFacFoeButton(x, y))

#Button
class FinFacFoeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.blurple, label='\u200b', row=y)
        self.x = x
        self.y = y
    
    async def callback(self, interaction: discord.Interaction):
        assert self.view is not None
        view: FinFacFoeView = self.view
        logging.info(f"Receiving interaction from {interaction.user.display_name}")
        #let gamestate class handle the logic
        await view.gamestate.on_update(self,interaction)

#------------------------------

def check_channel(interaction: discord.Interaction):
    logging.info(f"{interaction.channel.id} {VALID_CHANNEL_ID}")
    return interaction.channel.id == int(VALID_CHANNEL_ID)

@client.tree.command()
@app_commands.check(check_channel)
async def fin(interaction: discord.Interaction, challenger: discord.Member):

    gamestate = FinFacFoeGame(challenger,interaction.user)
    public_view = FinFacFoeView(gamestate,True)
    private_view = FinFacFoeView(gamestate,False)

    await interaction.response.send_message(f"{gamestate.boardmaster.display_name} challenged {gamestate.challenger.display_name}")
    msg = await interaction.followup.send(f'{gamestate.get_challenger_text()}> \u200b', view = public_view)
    gamestate.public_view = public_view
    gamestate.public_msg = msg
    hidden_msg = await interaction.followup.send(f'{gamestate.get_boardmaster_text()}> \u200b', view = private_view, ephemeral=True)
    gamestate.private_view = private_view
    gamestate.private_msg = hidden_msg

#------------------------------

#------------------------------

client.run(DISCORD_TOKEN)